import React, { useEffect, useRef } from 'react';
import {
  BrowserRouter as Router,
  Route,
  Routes,
  Navigate,
  useNavigate,
} from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Login from './pages/Login';
import Channels from './pages/Channels';
import ContentSources from './pages/ContentSources';
import Guide from './pages/Guide';
import Stats from './pages/Stats';
import DVR from './pages/DVR';
import Settings from './pages/Settings';
import PluginsPage from './pages/Plugins';
import PluginBrowsePage from './pages/PluginBrowse';
import ConnectPage from './pages/Connect';
import Users from './pages/Users';
import LogosPage from './pages/Logos';
import VODsPage from './pages/VODs';
import useAuthStore from './store/auth';
import useLocalStorage from './hooks/useLocalStorage';
import FloatingVideo from './components/FloatingVideo';
import { WebsocketProvider } from './WebSocket';
import { Box, AppShell, Center, Loader, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css'; // Ensure Mantine global styles load
import '@mantine/notifications/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/dates/styles.css';
import './index.css';
import mantineTheme from './mantineTheme';
import API from './api';
import { Notifications } from '@mantine/notifications';
import M3URefreshNotification from './components/M3URefreshNotification';
import 'allotment/dist/style.css';
import {
  DEFAULT_ROUTE,
  SSO_LANDING_PATH,
  ssoErrorMessage,
} from './utils/sso/ssoUtils';
import { showNotification } from './utils/notificationUtils';

const drawerWidth = 240;
const miniDrawerWidth = 60;
const defaultRoute = '/channels';

// Shown at /login/sso while the handoff runs, so neither route-table branch
// redirects away from the URL that still carries the loader's work.
const SsoHandoffLoader = () => (
  <Center style={{ height: '100vh' }} data-testid="sso-handoff-loader">
    <Loader aria-label="Signing you in" />
  </Center>
);

// The auth effect lives outside <Router>, so it reaches navigation through this.
const NavigateBridge = ({ navigateRef }) => {
  const navigate = useNavigate();
  navigateRef.current = navigate;
  return null;
};

const App = () => {
  const [open, setOpen] = useLocalStorage('dispatcharr_sidebar_open', true);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isInitialized = useAuthStore((s) => s.isInitialized);
  const logout = useAuthStore((s) => s.logout);
  const initData = useAuthStore((s) => s.initData);
  const initializeAuth = useAuthStore((s) => s.initializeAuth);
  const completeSsoHandoff = useAuthStore((s) => s.completeSsoHandoff);
  const navigateRef = useRef(null);
  const setSuperuserStatus = useAuthStore((s) => s.setSuperuserStatus);

  const authCheckStarted = useRef(false);
  const superuserCheckStarted = useRef(false);

  const toggleDrawer = () => {
    setOpen((prev) => !prev);
  };

  // Check if a superuser exists on first load.
  useEffect(() => {
    if (superuserCheckStarted.current) return;
    superuserCheckStarted.current = true;

    async function checkSuperuser() {
      try {
        const response = await API.fetchSuperUser();
        setSuperuserStatus(response);
      } catch (error) {
        console.error('Error checking superuser status:', error);
        // Preserve the existing fail-open UI behavior if the status check fails.
        setSuperuserStatus({ superuser_exists: true });
        // If authentication error, redirect to login
        if (error.status === 401) {
          localStorage.removeItem('accessToken');
          localStorage.removeItem('refreshToken');
          localStorage.removeItem('tokenExpiration');
          window.location.href = '/login';
        }
      }
    }
    checkSuperuser();
  }, [setSuperuserStatus]);

  // Authentication check
  useEffect(() => {
    if (authCheckStarted.current) return;
    authCheckStarted.current = true;

    const goTo = (target) => {
      if (navigateRef.current) {
        navigateRef.current(target, { replace: true });
      } else {
        window.location.replace(target);
      }
    };

    // Read before any await: once initData flips the store, the router's
    // wildcard redirect moves the URL away from /login under our feet.
    const landedCode =
      window.location.pathname === '/login'
        ? new URLSearchParams(window.location.search).get('sso_error')
        : null;

    const checkAuth = async () => {
      try {
        // The SSO handoff runs BEFORE any refresh: a stale password pair would
        // otherwise be refreshed first, and a refused refresh hard-navigates to
        // /login, aborting the very exchange meant to replace it.
        if (window.location.pathname === SSO_LANDING_PATH) {
          const handoff = await completeSsoHandoff();
          if (!handoff.ok) {
            goTo(`/login?sso_error=${encodeURIComponent(handoff.ssoError)}`);
            return;
          }
          if (await initializeAuth()) {
            try {
              await initData();
            } catch (error) {
              // Same cases the password login handles: a Streamer cannot use
              // the web UI; anything else is a failed bootstrap. Never leave
              // the user on the loader.
              useAuthStore.getState().clearSession();
              goTo(
                `/login?sso_error=${
                  error?.message === 'Unauthorized'
                    ? 'ui_access_denied'
                    : 'exchange_failed'
                }`
              );
              return;
            }
            if (handoff.intent === 'link') {
              showNotification({
                title: 'Single sign-on',
                message: 'Your single sign-on account is now linked.',
                color: 'green',
              });
            }
            goTo(handoff.next);
            return;
          }
          useAuthStore.getState().clearSession();
          goTo('/login?sso_error=exchange_failed');
          return;
        }

        const loggedIn = await initializeAuth();
        if (loggedIn) {
          await initData();
          // Logos are now loaded at the end of initData, no need for background loading
          // A refused link attempt comes back as /login?sso_error=...: the user is
          // still signed in, so the login page never mounts. Show the fixed copy
          // for the code (unknown codes get generic text, never the raw value),
          // drop the parameter and continue to the normal landing page.
          if (landedCode !== null) {
            showNotification({
              title: 'Single sign-on',
              message: ssoErrorMessage(landedCode),
              color: 'red',
            });
            goTo(DEFAULT_ROUTE);
          }
        } else {
          await logout();
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        await logout();
      }
    };

    checkAuth();
  }, [initializeAuth, initData, logout, completeSsoHandoff]);

  return (
    <MantineProvider
      defaultColorScheme="dark"
      theme={mantineTheme}
      withGlobalStyles
      withNormalizeCSS
    >
      <WebsocketProvider>
        <Router>
          <NavigateBridge navigateRef={navigateRef} />
          <AppShell
            header={{
              height: 0,
            }}
            navbar={{
              width:
                isAuthenticated && isInitialized
                  ? open
                    ? drawerWidth
                    : miniDrawerWidth
                  : 0,
            }}
          >
            {isAuthenticated && isInitialized && (
              <Sidebar
                drawerWidth={drawerWidth}
                miniDrawerWidth={miniDrawerWidth}
                collapsed={!open}
                toggleDrawer={toggleDrawer}
              />
            )}

            <AppShell.Main>
              <Box
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  // transition: 'margin-left 0.3s',
                  backgroundColor: '#18181b',
                  height: '100vh',
                  color: 'white',
                }}
              >
                <Box sx={{ p: 2, flex: 1, overflow: 'auto' }}>
                  <Routes>
                    {isAuthenticated && isInitialized ? (
                      <>
                        <Route path="/channels" element={<Channels />} />
                        <Route path="/sources" element={<ContentSources />} />
                        <Route path="/guide" element={<Guide />} />
                        <Route path="/dvr" element={<DVR />} />
                        <Route path="/stats" element={<Stats />} />
                        <Route
                          path="/plugins/browse"
                          element={<PluginBrowsePage />}
                        />
                        <Route path="/plugins" element={<PluginsPage />} />
                        <Route path="/connect" element={<ConnectPage />} />
                        <Route path="/users" element={<Users />} />
                        <Route path="/settings" element={<Settings />} />
                        <Route path="/logos" element={<LogosPage />} />
                        <Route path="/vods" element={<VODsPage />} />
                        <Route
                          path={SSO_LANDING_PATH}
                          element={<SsoHandoffLoader />}
                        />
                      </>
                    ) : (
                      <>
                        <Route path="/login" element={<Login />} />
                        <Route
                          path={SSO_LANDING_PATH}
                          element={<SsoHandoffLoader />}
                        />
                      </>
                    )}
                    <Route
                      path="*"
                      element={
                        <Navigate
                          to={
                            isAuthenticated && isInitialized
                              ? defaultRoute
                              : '/login'
                          }
                          replace
                        />
                      }
                    />
                  </Routes>
                </Box>
              </Box>
            </AppShell.Main>
          </AppShell>
          <M3URefreshNotification />
          <Notifications containerWidth={350} />
        </Router>
      </WebsocketProvider>

      <FloatingVideo />
    </MantineProvider>
  );
};

export default App;
