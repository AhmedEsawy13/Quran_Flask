/**
 * localStorage that never throws. Access raises a SecurityError when storage is
 * blocked (Safari with cookies off, some in-app webviews) and setItem can throw
 * on quota; preferences are a convenience, so both degrade to "nothing saved".
 */
export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable — the preference just is not remembered.
  }
}
