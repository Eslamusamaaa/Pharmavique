// Where the sign-in refresh token is kept: the phone's secure store, or the browser's local storage
// on the website (a browser has no secure store). If neither works the session lasts until the app
// or the tab is closed.
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const web = Platform.OS === 'web';

export async function readToken(key: string): Promise<string | null> {
  try {
    return web ? window.localStorage.getItem(key) : await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function writeToken(key: string, token: string | null): Promise<void> {
  try {
    if (web) {
      if (token) window.localStorage.setItem(key, token);
      else window.localStorage.removeItem(key);
    } else if (token) {
      await SecureStore.setItemAsync(key, token);
    } else {
      await SecureStore.deleteItemAsync(key);
    }
  } catch {
    // storage unavailable
  }
}
