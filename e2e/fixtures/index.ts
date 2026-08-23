import { test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ApiClient } from './api';
import { Seeder } from './seed';
import { makeUserClient } from './auth';
import { Waiter } from './wait';
import { WsListener } from './ws';
import { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
  asUser: (username: string, password: string) => Promise<ApiClient>;
  adminPage: Page;
  waitFor: Waiter;
  ws: WsListener;
  streamClient: StreamClient;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
  seed: async ({ api }, use, testInfo) => {
    await use(new Seeder(api, testInfo.workerIndex, testInfo.testId));
  },
  asUser: async ({ request }, use) => {
    await use((username: string, password: string) =>
      makeUserClient(request, username, password)
    );
  },
  // The seeded project already applies the admin storageState to `page`, so
  // this is an alias. It exists because the fixture contract names it, and
  // because a spec that says `adminPage` states its intent — a later project
  // could hand `page` a different principal without touching the tests.
  adminPage: async ({ page }, use) => {
    await use(page);
  },
  waitFor: async ({ api }, use) => {
    await use(new Waiter(api));
  },
  ws: async ({ baseURL }, use) => {
    const listener = new WsListener(baseURL!);
    await use(listener);
    listener.close();
  },
  streamClient: async ({ baseURL }, use) => {
    const client = new StreamClient(baseURL!);
    await use(client);
    await client.close();
  },
});

export { expect } from '@playwright/test';
export { ApiClient } from './api';
export { Seeder } from './seed';
export { makeUserClient } from './auth';
export { Waiter } from './wait';
export { WsListener } from './ws';
export { StreamClient, expectTsAligned, TS_PACKET_SIZE, TS_SYNC_BYTE } from './stream-client';
