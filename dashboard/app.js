// Boot: fetch site.json once and hand it to the page named in <main data-page>.
import * as overview from './pages/overview.js';
import * as story from './pages/story.js';
import * as explore from './pages/explore.js';
import * as compare from './pages/compare.js';
import * as defects from './pages/defects.js';
import { h } from './lib/dom.js';

const PAGES = { overview, story, explore, compare, defects };

export async function boot(pageName) {
  const root = document.querySelector('main');
  try {
    const res = await fetch('site.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`site.json: HTTP ${res.status}`);
    const site = await res.json();
    PAGES[pageName].render(site, root, new URLSearchParams(window.location.search));
  } catch (err) {
    root.replaceChildren(h('p', { class: 'error', text: `Could not load the dashboard data: ${err.message}. The Pages build may not have run yet.` }));
  }
}

if (typeof document !== 'undefined' && document.querySelector('main[data-page]')) {
  boot(document.querySelector('main').dataset.page);
}
