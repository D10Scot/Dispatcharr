import { describe, it, expect, vi, beforeEach } from 'vitest';
import useAuthStore from '../auth';
import useSettingsStore from '../settings';
import useChannelsStore from '../channels';
import usePlaylistsStore from '../playlists';
import useEPGsStore from '../epgs';
import useStreamProfilesStore from '../streamProfiles';
import useOutputProfilesStore from '../outputProfiles';
import useUserAgentsStore from '../userAgents';
import useServerGroupsStore from '../serverGroups';
import useUsersStore from '../users';
import API from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';
import { USER_LEVELS } from '../../constants';

vi.mock('../settings');
vi.mock('../channels');
vi.mock('../playlists');
vi.mock('../epgs');
vi.mock('../streamProfiles');
vi.mock('../outputProfiles');
vi.mock('../userAgents');
vi.mock('../serverGroups');
vi.mock('../users');
vi.mock('../../api');
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

const ok = () => vi.fn().mockResolvedValue();

describe('credential warnings after initData', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.getState = () => ({ fetchSettings: ok() });
    useChannelsStore.getState = () => ({
      fetchChannelGroups: ok(),
      fetchChannelProfiles: ok(),
      fetchChannelIds: ok(),
    });
    usePlaylistsStore.getState = () => ({ fetchPlaylists: ok() });
    useEPGsStore.getState = () => ({ fetchEPGs: ok(), fetchEPGData: ok() });
    useStreamProfilesStore.getState = () => ({ fetchProfiles: ok() });
    useOutputProfilesStore.getState = () => ({ fetchProfiles: ok() });
    useUserAgentsStore.getState = () => ({ fetchUserAgents: ok() });
    useServerGroupsStore.getState = () => ({ fetchServerGroups: ok() });
    useUsersStore.getState = () => ({ fetchUsers: ok() });
    useAuthStore.setState({ isInitialized: false, isInitializing: false });
  });

  it('shows one notification per entry for an Admin', async () => {
    API.me.mockResolvedValue({ username: 'a', user_level: USER_LEVELS.ADMIN });
    API.getAuthSettings.mockResolvedValue({
      credential_warnings: [{ slug: 'entra', state: 'expired', days_left: -2 }],
    });

    await useAuthStore.getState().initData();
    await vi.waitFor(() => expect(showNotification).toHaveBeenCalledTimes(1));

    const note = showNotification.mock.calls[0][0];
    expect(note.message).toContain('entra');
    expect(note.message).toContain('expired');
  });

  it('makes no getAuthSettings call for a Standard user', async () => {
    API.me.mockResolvedValue({
      username: 'u',
      user_level: USER_LEVELS.STANDARD,
    });

    await useAuthStore.getState().initData();
    await Promise.resolve();

    expect(API.getAuthSettings).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it('ignores a failure of the call', async () => {
    API.me.mockResolvedValue({ username: 'a', user_level: USER_LEVELS.ADMIN });
    API.getAuthSettings.mockRejectedValue(new Error('boom'));

    await expect(useAuthStore.getState().initData()).resolves.toBeUndefined();
    await Promise.resolve();
    expect(showNotification).not.toHaveBeenCalled();
  });
});
