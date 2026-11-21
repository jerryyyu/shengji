"""The app's offline bot entry (``web/ios/pybot/offline_bot.py``) decides as the server does.

The offline page asks the embedded bot for each bot-seat decision with a
request that rebuilds the round (deck, trump rank, starting banker, committed
actions).  ``bridge_harness`` runs seeded solo games through the real
``ws_endpoint`` and records, for every room-bot decision, that request and the
server bot's cards.  A fresh ``offline_bot`` session with a bot seeded like the
room bot, fed the requests in order, must choose the same cards every time:
the replayed round, the bot's carried-over state (its RNG and public-notice
ledger) and the copy-then-commit of each turn all match the server's.

MCBot stands in for the served bot here: it is seeded and stateful, so a lost
or extra RNG draw shows as a different choice.  With
``SHENGJI_OFFLINE_BOT_PAYLOAD`` set to a built payload directory
(``web/ios/pybot/build_payload.sh``) the served bot itself is checked too, on
fly.toml's own environment, where a choice may differ only where a wall-clock
limit fired.

The Standard level is checked the same way against a casual room whose Bots
are Standard (``bot_level`` "standard", built by the server's own
``make_relaxed_bot``): MCBot stands in for the served bot it wraps, and the
S136 scorer package plays the cards (``SHENGJI_RELAXED_SF_PACKAGE_PATH``, or
the built payload's copy).  Every choice must match, the near-best softmax
draws included.
"""

import copy
import gzip
import json
import os
import sys
from pathlib import Path

import pytest

PYBOT = Path(__file__).resolve().parents[2] / "web" / "ios" / "pybot"
sys.path.insert(0, str(PYBOT))
import bridge_harness  # noqa: E402
import gen_bridge_fixtures  # noqa: E402
import offline_bot  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.train import relaxed_play  # noqa: E402

FIXTURE = PYBOT.parents[2] / "web" / "src" / "offline" / "fixtures" / gen_bridge_fixtures.FIXTURE
BOT_SEED = 7
GAMES = [(41_000 + g, {"startLevel": "A" if g == 2 else None, "throws": g == 1}) for g in range(3)]


def _sf_package() -> Path | None:
    """The S136 scorer package, from its CI variable or a built payload."""
    value = os.environ.get("SHENGJI_RELAXED_SF_PACKAGE_PATH")
    if not value and os.environ.get("SHENGJI_OFFLINE_BOT_PAYLOAD"):
        value = offline_bot.standard_package(os.environ["SHENGJI_OFFLINE_BOT_PAYLOAD"])
    return Path(value) if value and Path(value).exists() else None


needs_sf = pytest.mark.skipif(_sf_package() is None,
                              reason="needs the S136 scorer package (SHENGJI_RELAXED_SF_PACKAGE_PATH "
                                     "or SHENGJI_OFFLINE_BOT_PAYLOAD)")


def _standard(served, seed=BOT_SEED):
    bot, error = offline_bot.standard_bot(served, str(_sf_package()), seed)
    assert error is None and isinstance(bot, relaxed_play.RelaxedBot)
    return bot


def _ask(req: dict, token: str) -> dict:
    return json.loads(offline_bot.decide(json.dumps({**req, "token": token})))


def _settle(token: str, accepted: bool) -> dict:
    return json.loads(offline_bot.settle(token, accepted))


def _replay(records, bot):
    """Every recorded decision asked and committed in order, as the server committed it."""
    offline_bot.start_session(bot)
    out = []
    for i, r in enumerate(records):
        out.append(_ask(r["request"], f"t{i}")["cards"])
        assert _settle(f"t{i}", True)["adopted"]
    return out


@pytest.fixture(scope="module")
def mc_games():
    return [bridge_harness.record_session(seed, 2, config, lambda: make_bot("mc", seed=BOT_SEED))[0]
            for seed, config in GAMES]


def test_offline_session_chooses_what_the_server_bot_chose(mc_games):
    kinds = {}
    for records in mc_games:
        assert [r["cards"] for r in records] == _replay(records, make_bot("mc", seed=BOT_SEED))
        for r in records:
            kinds[r["request"]["kind"]] = kinds.get(r["request"]["kind"], 0) + 1
    assert kinds["play"] >= 300 and kinds["bury"] >= 3 and kinds["declare"] >= 300
    # bot seats only: the driver's human seat never reaches the room bot
    assert all(r["request"]["seat"] != 0 for g in mc_games for r in g)


def test_a_differently_seeded_bot_is_told_apart(mc_games):
    records = mc_games[0]
    got = _replay(records, make_bot("mc", seed=BOT_SEED + 1))
    assert sum(a != r["cards"] for a, r in zip(got, records)) > 0


def test_replay_is_incremental_and_rebuilds_on_a_different_round(mc_games):
    records = [r for r in mc_games[0] if r["request"]["kind"] == "play"]
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    first, later = records[0]["request"], records[5]["request"]
    _ask(first, "a")
    cached = offline_bot._STATE["replay"]["round"]
    _ask(later, "b")
    assert offline_bot._STATE["replay"]["round"] is cached
    # a log that does not extend the cached one is replayed from the deal
    _ask(first, "c")
    assert offline_bot._STATE["replay"]["round"] is not cached
    rnd = offline_bot._STATE["replay"]["round"]
    assert rnd.turn == first["seat"] and rnd.phase == "play"


def test_a_request_for_a_seat_not_on_turn_is_refused(mc_games):
    req = copy.deepcopy(next(r["request"] for r in mc_games[0] if r["request"]["kind"] == "play"))
    req["seat"] = (req["seat"] + 1) % 4
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    with pytest.raises(offline_bot.RequestError):
        _ask(req, "x")
    bad = copy.deepcopy(req)
    bad["deck"] = bad["deck"][:-1] + ["S2"]
    with pytest.raises(offline_bot.RequestError):
        _ask(bad, "y")
    with pytest.raises(offline_bot.RequestError):
        offline_bot.decide(json.dumps(req))  # no token


def test_a_dropped_decision_leaves_the_bot_as_the_server_left_it(mc_games):
    """Every decision is first asked under a token the page drops (a late,
    refused or overtaken answer), then asked again and committed, with the
    verdicts carried on the next request as the page sends them.  The dropped
    searches draw from copies only, so every committed choice is still the
    server's."""
    records = mc_games[0]
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    got, verdicts = [], []
    for i, r in enumerate(records):
        _ask({**r["request"], "settle": verdicts}, f"late{i}")
        got.append(_ask({**r["request"], "settle": [[f"late{i}", False]]}, f"t{i}")["cards"])
        verdicts = [[f"t{i}", True]]
    assert got == [r["cards"] for r in records]


def test_the_dropped_copy_is_the_one_that_searched(mc_games):
    records = [r for r in mc_games[0] if r["request"]["kind"] == "play"]
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    bot = offline_bot._STATE["bot"]
    _ask(records[0]["request"], "late")
    assert offline_bot._STATE["bot"] is bot and set(offline_bot._STATE["pending"]) == {"late"}
    assert _settle("late", False) == {"token": "late", "adopted": False, "held": True}
    assert offline_bot._STATE["bot"] is bot and offline_bot._STATE["pending"] == {}


def test_an_unsettled_decision_is_dropped_once_the_log_moves_past_it(mc_games):
    records = [r for r in mc_games[0] if r["request"]["kind"] == "play"]
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    bot = offline_bot._STATE["bot"]
    _ask(records[0]["request"], "stale")
    _ask(records[1]["request"], "next")
    assert set(offline_bot._STATE["pending"]) == {"next"}
    # its verdict arrives too late to matter
    assert _settle("stale", True) == {"token": "stale", "adopted": False, "held": False}
    assert offline_bot._STATE["bot"] is bot
    assert _settle("next", True)["adopted"] and offline_bot._STATE["bot"] is not bot
    assert offline_bot._STATE["pending"] == {}


def test_committed_bridge_fixture_regenerates_identically():
    text = gzip.decompress(FIXTURE.read_bytes()).decode("utf-8")
    header = json.loads(text.split("\n", 1)[0])
    assert header["format"] == gen_bridge_fixtures.FORMAT
    assert gen_bridge_fixtures.fixture_text(header["games"], header["rounds"], header["seed"]) == text


@pytest.mark.skipif(not os.environ.get("SHENGJI_OFFLINE_BOT_PAYLOAD"),
                    reason="needs a built payload with the release weights")
def test_served_bot_offline_matches_server(tmp_path):
    """The served bot under fly.toml's own limits.  Its search stops at wall-clock
    limits (serving budgets, the greedy-finish deadline, the exact-lead cap), so
    two runs of one path can differ where a limit fires; every differing choice
    must have a limit firing on one side or the other."""
    make = bridge_harness.served_bot_factory(os.environ["SHENGJI_OFFLINE_BOT_PAYLOAD"], str(tmp_path),
                                             seed=13)
    seed, config = GAMES[0]
    records, _ = bridge_harness.record_session(seed, 1, config, make)
    offline_bot.start_session(make(), level="advanced")
    unexplained = []
    for i, r in enumerate(records):
        out = _ask({**r["request"], "level": "advanced"}, f"t{i}")
        _settle(f"t{i}", True)
        clock = {k: out[k] for k in ("fallback", "exact_lead", "leaf_deadline") if k in out}
        if out["cards"] != r["cards"] and not clock and not r["clock"]:
            unexplained.append((r["request"]["kind"], out["cards"], r["cards"]))
    assert len(records) > 100 and unexplained == []


def test_replayed_commit_does_not_replace_a_later_pending_copy(mc_games):
    records = [r for r in mc_games[0] if r["request"]["kind"] == "play"]
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED))
    _ask(records[0]["request"], "accepted")
    committed = offline_bot._STATE["pending"]["accepted"]["bot"]
    _ask({**records[1]["request"], "settle": [["accepted", True]]}, "lost-response")
    assert offline_bot._STATE["bot"] is committed
    # The transport cannot tell whether the request reached Python.
    _ask({**records[1]["request"], "settle": [["accepted", True], ["lost-response", False]]}, "next")
    assert offline_bot._STATE["bot"] is committed
    pending = offline_bot._STATE["pending"]["next"]["bot"]
    assert not _settle("accepted", True)["adopted"]
    assert offline_bot._STATE["pending"]["next"]["bot"] is pending
    assert _settle("next", True)["adopted"]
    assert offline_bot._STATE["bot"] is pending


def test_the_offline_levels_are_the_servers():
    from shengji.api import matchmaking, server
    assert set(offline_bot.LEVELS) == set(matchmaking.BOT_LEVELS)
    assert offline_bot.DEFAULT_LEVEL == matchmaking.CASUAL_BOT_LEVEL == "standard"
    assert Path(server.RELAXED_SF_PACKAGE).name == relaxed_play.CASUAL_PACKAGE
    assert server.RELAXED_SF_SHA256 == relaxed_play.CASUAL_SHA256
    assert server.RELAXED_BOT == relaxed_play.casual_suffix()
    # the payload bundles the package, pinned like the release weights
    manifest = (PYBOT / "MANIFEST.sha256").read_text().split("\n")
    assert f"{relaxed_play.CASUAL_SHA256}  {relaxed_play.CASUAL_PACKAGE}" in manifest


def test_a_missing_scorer_package_plays_the_served_bot_as_the_server_does(tmp_path):
    served = make_bot("mc", seed=BOT_SEED)
    bot, error = offline_bot.standard_bot(served, str(tmp_path / relaxed_play.CASUAL_PACKAGE), BOT_SEED)
    assert bot is served and error


@pytest.fixture(scope="module")
def mc_standard_games():
    package = str(_sf_package())
    return [bridge_harness.record_session(seed, 2, config, lambda: make_bot("mc", seed=BOT_SEED),
                                          standard=(package, BOT_SEED))[0]
            for seed, config in GAMES]


def _replay_level(records, bots, level):
    offline_bot.start_sessions(bots)
    out = []
    for i, r in enumerate(records):
        out.append(_ask({**r["request"], "level": level}, f"t{i}")["cards"])
        assert _settle(f"t{i}", True)["adopted"]
    return out


@needs_sf
def test_standard_offline_chooses_what_a_standard_room_chose(mc_standard_games):
    """Both levels in the session, as ``init`` builds them; Standard decides."""
    kinds, n = {}, 0
    for records in mc_standard_games:
        served = make_bot("mc", seed=BOT_SEED)
        bots = {"advanced": make_bot("mc", seed=BOT_SEED), "standard": _standard(served)}
        got = _replay_level(records, bots, "standard")
        assert got == [r["cards"] for r in records]
        for r in records:
            kinds[r["request"]["kind"]] = kinds.get(r["request"]["kind"], 0) + 1
        n += len(records)
    assert n >= 600 and kinds["play"] >= 300 and kinds["bury"] >= 3 and kinds["declare"] >= 200


@needs_sf
def test_a_request_without_a_level_plays_standard(mc_standard_games):
    records = mc_standard_games[0]
    offline_bot.start_sessions({"advanced": make_bot("mc", seed=BOT_SEED),
                                "standard": _standard(make_bot("mc", seed=BOT_SEED))})
    got = []
    for i, r in enumerate(records):
        out = _ask(r["request"], f"t{i}")
        assert out["level"] == "standard"
        got.append(out["cards"])
        _settle(f"t{i}", True)
    assert got == [r["cards"] for r in records]


@needs_sf
def test_standard_is_told_apart_from_advanced_and_from_another_seed(mc_standard_games):
    records = mc_standard_games[0]
    plays = [i for i, r in enumerate(records) if r["request"]["kind"] == "play"]
    advanced = _replay_level(records, {"advanced": make_bot("mc", seed=BOT_SEED)}, "advanced")
    assert sum(advanced[i] != records[i]["cards"] for i in plays) > 0
    # the softmax's own stream: the same served bot, the scorer seeded differently
    reseeded = _replay_level(records, {"standard": _standard(make_bot("mc", seed=BOT_SEED), BOT_SEED + 1)},
                             "standard")
    assert sum(reseeded[i] != records[i]["cards"] for i in plays) > 0


@needs_sf
def test_the_levels_keep_separate_sessions(mc_standard_games, mc_games):
    """Interleaved tables at both levels: each level's bot sees only its own
    decisions, and a verdict reaches the level that holds its token."""
    std, adv = mc_standard_games[0], mc_games[0]
    offline_bot.start_sessions({"advanced": make_bot("mc", seed=BOT_SEED),
                                "standard": _standard(make_bot("mc", seed=BOT_SEED))})
    got_std, got_adv, verdicts = [], [], []
    for i in range(max(len(std), len(adv))):
        for level, records, got in (("standard", std, got_std), ("advanced", adv, got_adv)):
            if i < len(records):
                token = f"{level[0]}{i}"
                got.append(_ask({**records[i]["request"], "level": level, "settle": verdicts}, token)["cards"])
                verdicts = [[token, True]]
    assert got_std == [r["cards"] for r in std]
    assert got_adv == [r["cards"] for r in adv]
    with pytest.raises(offline_bot.RequestError):
        _ask({**std[0]["request"], "level": "expert"}, "x")
    offline_bot.start_session(make_bot("mc", seed=BOT_SEED), level="advanced")
    with pytest.raises(offline_bot.RequestError):
        _ask(std[0]["request"], "y")  # Standard, which this session has no bot for


@pytest.mark.skipif(not os.environ.get("SHENGJI_OFFLINE_BOT_PAYLOAD"),
                    reason="needs a built payload with the release weights")
def test_served_standard_offline_matches_a_standard_room(tmp_path):
    """Standard on release weights, through ``init``: the served bot declares
    and buries under its wall-clock limits (a differing declare or bury must
    show a limit firing), and the scorer plays every card exactly."""
    payload = os.environ["SHENGJI_OFFLINE_BOT_PAYLOAD"]
    make = bridge_harness.served_bot_factory(payload, str(tmp_path / "rec"), seed=13)
    package = offline_bot.standard_package(payload)
    records = []
    for seed, config in GAMES:
        records.append(bridge_harness.record_session(seed, 1, config, make, standard=(package, 13))[0])
    ident = json.loads(offline_bot.init(payload, str(tmp_path / "out"), 13))
    assert ident["matches_fly_toml"] and ident["standard_error"] is None
    assert ident["levels"]["standard"] == f"{ident['bot']}-{relaxed_play.casual_suffix()}"
    unexplained, plays = [], 0
    for g, game in enumerate(records):
        if g:
            ident = json.loads(offline_bot.init(payload, str(tmp_path / "out"), 13))
        for i, r in enumerate(game):
            out = _ask({**r["request"], "level": "standard"}, f"g{g}t{i}")
            _settle(f"g{g}t{i}", True)
            kind = r["request"]["kind"]
            plays += kind == "play"
            clock = {k: out[k] for k in ("fallback", "exact_lead", "leaf_deadline") if k in out}
            if out["cards"] != r["cards"] and (kind == "play" or (not clock and not r["clock"])):
                unexplained.append((g, i, kind, out["cards"], r["cards"]))
    assert sum(len(g) for g in records) >= 200 and plays >= 100 and unexplained == []
