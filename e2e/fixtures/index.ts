import { test as base } from '@playwright/test';
import { ApiClient } from './api';
import { Seeder } from './seed';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
  seed: async ({ api }, use, testInfo) => {
    await use(new Seeder(api, testInfo.workerIndex, testInfo.testId));
  },
});

export { expect } from '@playwright/test';
export { ApiClient } from './api';
export { Seeder } from './seed';
