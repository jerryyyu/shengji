// A short tap when the turn arrives, on the native shell only. The web has no
// Capacitor runtime, so this is a no-op there and the plugin is loaded on
// demand: the web bundle's startup path never touches it.

interface NativeBridge {
  isNativePlatform?: () => boolean;
}

/** True inside the Capacitor iOS/Android shell, false in any browser. */
export function isNativeShell(): boolean {
  const bridge = (window as unknown as { Capacitor?: NativeBridge }).Capacitor;
  return bridge?.isNativePlatform?.() === true;
}

export function hapticTurn(): void {
  if (!isNativeShell()) return;
  void import("@capacitor/haptics")
    .then(({ Haptics, ImpactStyle }) => Haptics.impact({ style: ImpactStyle.Medium }))
    .catch(() => {
      /* a device without a Taptic Engine, or the plugin missing: silence */
    });
}
