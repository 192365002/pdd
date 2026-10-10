// ─── Auth Context — Smart Firebase + Dev-mode fallback ───────────────────────
import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { healthCheck } from './api';

const AuthContext = createContext(null);

// Helper to extract a clean display name from an email address
export function formatNameFromEmail(email) {
  if (!email) return 'Shield User';
  const prefix = email.split('@')[0];
  if (!prefix) return 'Shield User';
  const parts = prefix.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return 'Shield User';
  return parts
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join(' ');
}

// Check if Firebase env vars are configured
const hasFirebaseConfig = !!(
  import.meta.env.VITE_FIREBASE_API_KEY &&
  import.meta.env.VITE_FIREBASE_API_KEY !== 'AIzaSy...' &&
  import.meta.env.VITE_FIREBASE_PROJECT_ID &&
  import.meta.env.VITE_FIREBASE_PROJECT_ID !== 'your-project-id'
);

// ─── Provider ─────────────────────────────────────────────────────────────────
export function AuthProvider({ children }) {
  const [user, setUser]                 = useState(null);
  const [loading, setLoading]           = useState(true);
  const [backendOnline, setBackendOnline] = useState(null);

  // Backend health check on mount
  useEffect(() => {
    healthCheck()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, []);

  // Restore session from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem('ss_user');
    if (stored) {
      try { setUser(JSON.parse(stored)); } catch {}
    }
    setLoading(false);
  }, []);

  // ─── Internal setter ─────────────────────────────────────────────────────────
  const persistUser = useCallback((userData, token) => {
    localStorage.setItem('ss_user', JSON.stringify(userData));
    localStorage.setItem('auth_token', token);
    setUser(userData);
  }, []);

  // ─── Email/Password Login ─────────────────────────────────────────────────────
  const login = async (email, password) => {
    if (hasFirebaseConfig) {
      const { initializeApp, getApps }          = await import('firebase/app');
      const { getAuth, signInWithEmailAndPassword } = await import('firebase/auth');

      const app  = getApps().length ? getApps()[0] : initializeApp({
        apiKey:            import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain:        import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId:         import.meta.env.VITE_FIREBASE_PROJECT_ID,
        storageBucket:     import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
        messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
        appId:             import.meta.env.VITE_FIREBASE_APP_ID,
      });
      const auth = getAuth(app);
      const cred = await signInWithEmailAndPassword(auth, email, password);
      const token = await cred.user.getIdToken();
      const userData = {
        uid: cred.user.uid,
        email: cred.user.email,
        displayName: cred.user.displayName || formatNameFromEmail(email),
      };
      persistUser(userData, token);
      return userData;
    } else {
      // ── Demo / Local fallback mode (no Firebase configured) ──
      await new Promise((r) => setTimeout(r, 600));
      const cleanEmail = email.replace(/[^a-zA-Z0-9]/g, '_');
      const token = 'user_token_' + cleanEmail;
      
      let registeredMap = {};
      try {
        registeredMap = JSON.parse(localStorage.getItem('ss_registered_users') || '{}');
      } catch {}
      const existingUser = registeredMap[email.toLowerCase()];
      const resolvedName = existingUser?.name || formatNameFromEmail(email);

      const userData = { uid: cleanEmail, email, displayName: resolvedName };
      persistUser(userData, token);
      return userData;
    }
  };

  // ─── Sign Up ──────────────────────────────────────────────────────────────────
  const signUp = async (email, password, name = '') => {
    const finalName = name.trim() || formatNameFromEmail(email);
    if (hasFirebaseConfig) {
      const { initializeApp, getApps }               = await import('firebase/app');
      const { getAuth, createUserWithEmailAndPassword, updateProfile } = await import('firebase/auth');
      const app  = getApps().length ? getApps()[0] : initializeApp({
        apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
        storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
        messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
        appId: import.meta.env.VITE_FIREBASE_APP_ID,
      });
      const auth = getAuth(app);
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      try {
        await updateProfile(cred.user, { displayName: finalName });
      } catch (err) {
        console.warn('Could not update Firebase profile name:', err);
      }
      const token = await cred.user.getIdToken();
      const userData = { uid: cred.user.uid, email: cred.user.email, displayName: finalName };
      persistUser(userData, token);
      return userData;
    } else {
      await new Promise((r) => setTimeout(r, 600));
      const cleanEmail = email.replace(/[^a-zA-Z0-9]/g, '_');
      const token = 'user_token_' + cleanEmail;

      // Save to local registry so future logins remember the entered name
      try {
        const registeredMap = JSON.parse(localStorage.getItem('ss_registered_users') || '{}');
        registeredMap[email.toLowerCase()] = { name: finalName, email };
        localStorage.setItem('ss_registered_users', JSON.stringify(registeredMap));
      } catch {}

      const userData = { uid: cleanEmail, email, displayName: finalName };
      persistUser(userData, token);
      return userData;
    }
  };

  // ─── Google Sign-In ───────────────────────────────────────────────────────────
  const loginWithGoogle = async () => {
    if (hasFirebaseConfig) {
      const { initializeApp, getApps }               = await import('firebase/app');
      const { getAuth, GoogleAuthProvider, signInWithPopup } = await import('firebase/auth');
      const app      = getApps().length ? getApps()[0] : initializeApp({
        apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
        storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
        messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
        appId: import.meta.env.VITE_FIREBASE_APP_ID,
      });
      const auth     = getAuth(app);
      const provider = new GoogleAuthProvider();
      const cred     = await signInWithPopup(auth, provider);
      const token    = await cred.user.getIdToken();
      const userData = {
        uid: cred.user.uid,
        email: cred.user.email,
        displayName: cred.user.displayName || formatNameFromEmail(cred.user.email) || 'Shield User',
      };
      persistUser(userData, token);
      return userData;
    } else {
      await new Promise((r) => setTimeout(r, 500));
      const googleEmail = 'user@socialshield.ai';
      let registeredMap = {};
      try {
        registeredMap = JSON.parse(localStorage.getItem('ss_registered_users') || '{}');
      } catch {}
      const resolvedName = registeredMap[googleEmail]?.name || 'Shield User';
      const userData = { uid: 'google_user_' + Date.now(), email: googleEmail, displayName: resolvedName };
      persistUser(userData, 'google_token_' + Date.now());
      return userData;
    }
  };

  // ─── Logout ───────────────────────────────────────────────────────────────────
  const logout = async () => {
    if (hasFirebaseConfig) {
      try {
        const { getApps }  = await import('firebase/app');
        const { getAuth, signOut } = await import('firebase/auth');
        if (getApps().length) await signOut(getAuth(getApps()[0]));
      } catch {}
    }
    localStorage.removeItem('auth_token');
    localStorage.removeItem('ss_user');
    setUser(null);
  };

  // ─── Update User Fields ────────────────────────────────────────────────────────
  const updateUser = async (fields) => {
    if (hasFirebaseConfig) {
      try {
        const { getApps } = await import('firebase/app');
        const { getAuth, updateProfile } = await import('firebase/auth');
        if (getApps().length) {
          const auth = getAuth(getApps()[0]);
          if (auth.currentUser && fields.displayName) {
            await updateProfile(auth.currentUser, { displayName: fields.displayName });
          }
        }
      } catch (err) {
        console.error("Firebase profile update failed:", err);
      }
    }
    
    // Also update local registered map if displayName changed
    if (user?.email && fields.displayName) {
      try {
        const registeredMap = JSON.parse(localStorage.getItem('ss_registered_users') || '{}');
        registeredMap[user.email.toLowerCase()] = {
          ...registeredMap[user.email.toLowerCase()],
          name: fields.displayName,
          email: user.email,
        };
        localStorage.setItem('ss_registered_users', JSON.stringify(registeredMap));
      } catch {}
    }

    setUser((u) => {
      const next = { ...u, ...fields };
      localStorage.setItem('ss_user', JSON.stringify(next));
      return next;
    });
  };

  return (
    <AuthContext.Provider value={{ user, loading, backendOnline, login, signUp, loginWithGoogle, logout, updateUser, formatNameFromEmail }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
