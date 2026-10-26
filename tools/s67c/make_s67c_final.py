#!/usr/bin/env python3
"""make_s67c_final.py -- fill the three extension pins of claude_s67c_perf.sh (the reviewed draft, TO_BE_PINNED) from the perf build log of
/root/claude-sc8p-src-8a50fe8a (claude_build_sc8p_perf.sh writes 'ext engine/_fast <sha>', 'ext ai/_cwv_math <sha>', 'ext ai/_endgame_fast
<sha>' and BUILD_RC=0 to /root/claude-sc8p-src-8a50fe8a-build.log), writing claude_s67c_perf.final.sh.  The ONLY change is the three pin
values on the one EXT_* line (asserted: the final differs from the draft in exactly that line, and in it exactly the three TO_BE_PINNED
tokens).  The final file's sha256 is the RELEASE token; make_s67c_reservation.py and test_s67c_packet.py then bind the reservation to it.
The same step writes s67c_read.final.py from the reader draft, replacing ONLY its TRUSTED_LAUNCHER_SHA256 = "TO_BE_PINNED" line with the
final launcher's sha256 (asserted: one line differs), so the pinned reader binds the reservation and the armed status line to the
independently reviewed final launcher; the pin delta review covers the launcher's pin line and the reader's trusted line.
= s66dev's make_s66dev_final.py with the lane names and the tree changed.

Usage: python3 make_s67c_final.py <build log copy, or '-' for stdin>      (refuses to overwrite; the log must hold BUILD_RC=0 and exactly
       one 'ext' line per extension, each a 64-hex sha, all three distinct)
       python3 make_s67c_final.py --rehearse <out path>   : the same transformation with three dummy shas into <out path> (the packet test)"""
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRAFT = HERE / "claude_s67c_perf.sh"
FINAL = HERE / "claude_s67c_perf.final.sh"
READER, READER_FINAL = HERE / "s67c_read.py", HERE / "s67c_read.final.py"
TRUSTED_LINE = 'TRUSTED_LAUNCHER_SHA256 = "TO_BE_PINNED"   #'
EXTS = ("engine/_fast", "ai/_cwv_math", "ai/_endgame_fast")
ORDER = ("EXT_ENGINE_SHA", "EXT_CWV_SHA", "EXT_ENDGAME_SHA")


def pins_from_log(text):
    if "BUILD_RC=0" not in text.splitlines():
        raise SystemExit("REFUSING: the build log has no BUILD_RC=0 line")
    pins = {}
    for ext in EXTS:
        hits = re.findall(r"^\S+ ext " + re.escape(ext) + r" ([0-9a-f]{64})$", text, re.M)
        if len(hits) != 1:
            raise SystemExit(f"REFUSING: {len(hits)} 'ext {ext} <sha256>' lines in the build log (need exactly one)")
        pins[ext] = hits[0]
    if len(set(pins.values())) != 3:
        raise SystemExit("REFUSING: the three extension shas are not distinct")
    return [pins[e] for e in EXTS]


def fill(draft_text, shas):
    lines = draft_text.split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith("EXT_ENGINE_SHA=TO_BE_PINNED; EXT_CWV_SHA=TO_BE_PINNED; EXT_ENDGAME_SHA=TO_BE_PINNED   # ")]
    if len(idx) != 1:
        raise SystemExit("REFUSING: the draft does not hold exactly one TO_BE_PINNED pin line")
    i = idx[0]
    line = lines[i]
    assert line.count("TO_BE_PINNED") == 3
    for name, sha in zip(ORDER, shas):
        assert re.fullmatch(r"[0-9a-f]{64}", sha), sha
        line = line.replace(f"{name}=TO_BE_PINNED", f"{name}={sha}", 1)
    lines[i] = line
    out = "\n".join(lines)
    # the final differs from the draft in exactly that line
    d, f = draft_text.split("\n"), out.split("\n")
    assert len(d) == len(f) and [j for j in range(len(d)) if d[j] != f[j]] == [i], "the final must differ from the draft in the pin line only"
    assert "TO_BE_PINNED" not in line and out.count("TO_BE_PINNED") == draft_text.count("TO_BE_PINNED") - 3   # the guard's two mentions and the header's remain
    return out


def pin_reader(reader_text, launcher_sha):
    """The reader draft with its one TRUSTED_LAUNCHER_SHA256 line pointed at the final launcher's sha256; nothing else changes."""
    assert re.fullmatch(r"[0-9a-f]{64}", launcher_sha), launcher_sha
    lines = reader_text.split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith(TRUSTED_LINE)]
    if len(idx) != 1:
        raise SystemExit("REFUSING: the reader draft does not hold exactly one TRUSTED_LAUNCHER_SHA256 = \"TO_BE_PINNED\" line")
    i = idx[0]
    lines[i] = lines[i].replace('"TO_BE_PINNED"', f'"{launcher_sha}"', 1)
    out = "\n".join(lines)
    d, f = reader_text.split("\n"), out.split("\n")
    assert len(d) == len(f) and [j for j in range(len(d)) if d[j] != f[j]] == [i], "the pinned reader must differ from the draft in the trusted line only"
    assert out.count("TO_BE_PINNED") == reader_text.count("TO_BE_PINNED") - 1
    return out


def main(argv):
    draft = DRAFT.read_text()
    if argv[:1] == ["--rehearse"]:
        dest = Path(argv[1])
        shas = [hashlib.sha256(f"rehearsal-{e}".encode()).hexdigest() for e in EXTS]
        dest.open("x").write(fill(draft, shas))
        lsha = hashlib.sha256(dest.read_bytes()).hexdigest()
        Path(str(dest) + ".reader.py").open("x").write(pin_reader(READER.read_text(), lsha))
        print(f"rehearsal final written to {dest} (dummy pins {[s[:8] for s in shas]}); sha256 {lsha}; pinned reader beside it ({dest}.reader.py)")
        return
    if len(argv) != 1:
        raise SystemExit(__doc__)
    text = sys.stdin.read() if argv[0] == "-" else Path(argv[0]).read_text()
    shas = pins_from_log(text)
    final = fill(draft, shas)
    lsha = hashlib.sha256(final.encode()).hexdigest()
    reader = pin_reader(READER.read_text(), lsha)
    FINAL.open("x").write(final)
    READER_FINAL.open("x").write(reader)
    print(f"{FINAL.name} sha256 {lsha} (pins {[s[:8] for s in shas]}; from draft {hashlib.sha256(draft.encode()).hexdigest()[:8]}: the pin line only)")
    print(f"{READER_FINAL.name} sha256 {hashlib.sha256(reader.encode()).hexdigest()} (from the reader draft {hashlib.sha256(READER.read_bytes()).hexdigest()[:8]}: the TRUSTED_LAUNCHER_SHA256 line only, now {lsha[:12]}...)")


if __name__ == "__main__":
    main(sys.argv[1:])
