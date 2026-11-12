import { describe, it, expect } from 'vitest';
import {
  credentialPayload,
  credentialReducer,
  credentialView,
  initialCredentialState,
} from '../credentialEdits';

// The provider form's credential state (spec 5.2). The tables below are the
// state table of SSO S3 fix round 3; the last block enumerates every ordering
// of edits, saves and reloads up to a fixed length against a model of the
// server's PATCH (apps/accounts/oidc/serializers.py, update()).

const D = '2026-12-01';
const X = '2027-06-30';
const ABSENT = 'ABSENT';

const stored = ({ method = 'client_secret_post', date = null } = {}) => ({
  id: 7,
  kind: 'entra',
  client_auth_method: method,
  client_secret_set: true,
  client_secret_expires_at: date,
});

// What the server does with a PATCH (serializers.py update()): an absent key
// keeps the stored value; a new client_secret without a date in the same
// request resets the date to null.
const serverPatch = (provider, payload) => {
  const next = { ...provider };
  if ('client_auth_method' in payload) {
    next.client_auth_method = payload.client_auth_method;
  }
  if ('client_secret' in payload) {
    next.client_secret_set = true;
    next.client_secret_expires_at =
      'client_secret_expires_at' in payload
        ? payload.client_secret_expires_at
        : null;
  } else if ('client_secret_expires_at' in payload) {
    next.client_secret_expires_at = payload.client_secret_expires_at;
  }
  return next;
};

const OPS = {
  type: (v) => ({ type: 'secret', value: v }),
  erase: () => ({ type: 'secret', value: '' }),
  date: (v) => ({ type: 'date', value: v }),
  radio: (v) => ({ type: 'credential', value: v }),
};

const run = (provider, steps) =>
  steps.reduce(
    (s, [op, v]) => credentialReducer(s, OPS[op](v)),
    initialCredentialState(provider)
  );

const keyOf = (payload, key) =>
  Object.hasOwn(payload, key) ? payload[key] : ABSENT;

describe('credential state table S: secret and expiry date keys', () => {
  // [name, steps, stored D: [client_secret, client_secret_expires_at, shown],
  //  stored none: [...]]. Rows A-K of fix round 2 are 1-6, 7, 8, 13-16.
  const S = [
    ['1 untouched', [], [ABSENT, ABSENT, D], [ABSENT, ABSENT, '']],
    ['2 type', [['type', 'n']], ['n', null, ''], ['n', null, '']],
    [
      '3 type, erase',
      [['type', 'n'], ['erase']],
      [ABSENT, ABSENT, D],
      [ABSENT, ABSENT, ''],
    ],
    ['4 set X', [['date', X]], [ABSENT, X, X], [ABSENT, X, X]],
    ['5 clear', [['date', '']], [ABSENT, null, ''], [ABSENT, ABSENT, '']],
    ['6 set D', [['date', D]], [ABSENT, ABSENT, D], [ABSENT, D, D]],
    [
      '7 set X, type',
      [
        ['date', X],
        ['type', 'n'],
      ],
      ['n', X, X],
      ['n', X, X],
    ],
    [
      '8 type, set X',
      [
        ['type', 'n'],
        ['date', X],
      ],
      ['n', X, X],
      ['n', X, X],
    ],
    [
      '9 clear, type',
      [
        ['date', ''],
        ['type', 'n'],
      ],
      ['n', null, ''],
      ['n', null, ''],
    ],
    [
      '10 type, clear',
      [
        ['type', 'n'],
        ['date', ''],
      ],
      ['n', null, ''],
      ['n', null, ''],
    ],
    // D entered before the secret was typed is the old secret's date (stored
    // D); with no stored date it is a date the administrator chose.
    [
      '11 set D, type',
      [
        ['date', D],
        ['type', 'n'],
      ],
      ['n', null, ''],
      ['n', D, D],
    ],
    [
      '12 type, set D',
      [
        ['type', 'n'],
        ['date', D],
      ],
      ['n', D, D],
      ['n', D, D],
    ],
    [
      '13 set X, type, erase',
      [['date', X], ['type', 'n'], ['erase']],
      [ABSENT, X, X],
      [ABSENT, X, X],
    ],
    [
      '14 type, set X, erase',
      [['type', 'n'], ['date', X], ['erase']],
      [ABSENT, X, X],
      [ABSENT, X, X],
    ],
    [
      '15 type, erase, type',
      [['type', 'a'], ['erase'], ['type', 'b']],
      ['b', null, ''],
      ['b', null, ''],
    ],
    [
      '16 set X, set D',
      [
        ['date', X],
        ['date', D],
      ],
      [ABSENT, ABSENT, D],
      [ABSENT, D, D],
    ],
  ];

  const cases = [];
  for (const [name, steps, withD, withNone] of S) {
    for (const [label, date, expected] of [
      ['stored D', D, withD],
      ['stored none', null, withNone],
    ]) {
      for (const method of ['client_secret_post', 'private_key_jwt']) {
        for (const radio of [undefined, 'certificate', 'secret']) {
          cases.push([
            `${name} | ${label} | ${method} | radio ${radio ?? 'untouched'}`,
            stored({ method, date }),
            radio ? [...steps, ['radio', radio]] : steps,
            expected,
          ]);
        }
      }
    }
  }

  // The radio and the stored method are in every row: neither may change the
  // secret or date keys, nor the date shown.
  it.each(cases)('%s', (_n, provider, steps, [secret, expires, shown]) => {
    const state = run(provider, steps);
    const payload = credentialPayload(state, 'entra');
    const view = credentialView(state, 'entra');
    expect(keyOf(payload, 'client_secret')).toBe(secret);
    expect(keyOf(payload, 'client_secret_expires_at')).toBe(expires);
    expect(view.secretExpiry).toBe(shown);
  });
});

describe('credential state table R: the radio and client_auth_method', () => {
  // [stored method, radio steps, radio shown, client_auth_method key]
  it.each([
    ['client_secret_post', [], 'secret', 'client_secret_post'],
    ['client_secret_post', ['certificate'], 'certificate', ABSENT],
    [
      'client_secret_post',
      ['certificate', 'secret'],
      'secret',
      'client_secret_post',
    ],
    ['private_key_jwt', [], 'certificate', ABSENT],
    ['private_key_jwt', ['secret'], 'secret', 'client_secret_post'],
    ['private_key_jwt', ['secret', 'certificate'], 'certificate', ABSENT],
    [null, [], 'certificate', ABSENT],
    [null, ['secret'], 'secret', 'client_secret_post'],
  ])('stored %s, radio %j', (method, radios, shown, sent) => {
    const provider = method ? stored({ method }) : null;
    const state = run(
      provider,
      radios.map((r) => ['radio', r])
    );
    expect(credentialView(state, 'entra').credential).toBe(shown);
    expect(keyOf(credentialPayload(state, 'entra'), 'client_auth_method')).toBe(
      sent
    );
  });

  it('a generic provider defaults to HTTP Basic when switched from the certificate', () => {
    const state = run(stored({ method: 'private_key_jwt' }), [
      ['radio', 'secret'],
    ]);
    expect(credentialPayload(state, 'generic').client_auth_method).toBe(
      'client_secret_basic'
    );
  });

  it('the certificate view reports a pending secret and a pending date', () => {
    const typed = run(stored({ date: D }), [
      ['type', 'n'],
      ['radio', 'certificate'],
    ]);
    expect(credentialView(typed, 'entra')).toMatchObject({
      credential: 'certificate',
      pendingSecret: true,
    });
    const dated = run(stored({ date: D }), [
      ['date', X],
      ['radio', 'certificate'],
    ]);
    expect(credentialView(dated, 'entra')).toMatchObject({
      pendingSecret: false,
      pendingDate: true,
    });
    expect(credentialView(run(stored({ date: D }), []), 'entra')).toMatchObject(
      { pendingSecret: false, pendingDate: false }
    );
  });
});

describe('credential state table Q: consecutive saves and reloads', () => {
  const save = (state) => {
    const payload = credentialPayload(state, 'entra');
    const answer = serverPatch(state.provider, payload);
    return [
      payload,
      credentialReducer(state, { type: 'saved', provider: answer }),
    ];
  };

  it('the round-3 sequence: type, certificate, save, back, save', () => {
    let state = run(stored({ date: D }), [
      ['type', 'n'],
      ['radio', 'certificate'],
    ]);
    const [first, afterFirst] = save(state);
    expect(first).toEqual({
      client_secret: 'n',
      client_secret_expires_at: null,
    });
    expect(credentialView(afterFirst, 'entra')).toMatchObject({
      credential: 'secret',
      secret: '',
      secretExpiry: '',
    });
    state = credentialReducer(afterFirst, OPS.radio('secret'));
    const [second] = save(state);
    expect(second).toEqual({ client_auth_method: 'client_secret_post' });
  });

  it('an untouched second save keeps the stored date and sends no secret', () => {
    const [, after] = save(run(stored({ date: D }), [['date', X]]));
    expect(credentialView(after, 'entra').secretExpiry).toBe(X);
    const [second] = save(after);
    expect(Object.hasOwn(second, 'client_secret')).toBe(false);
    expect(Object.hasOwn(second, 'client_secret_expires_at')).toBe(false);
  });

  it('a save followed by a reload shows the reloaded provider', () => {
    const [, after] = save(run(stored({ date: D }), [['type', 'n']]));
    const reloaded = credentialReducer(after, {
      type: 'reloaded',
      provider: stored({ method: 'private_key_jwt', date: X }),
    });
    expect(credentialView(reloaded, 'entra')).toMatchObject({
      credential: 'certificate',
      secret: '',
      secretExpiry: X,
    });
  });

  it('a reload keeps unsaved edits and updates untouched fields', () => {
    const typed = run(stored({ date: D }), [
      ['type', 'n'],
      ['radio', 'certificate'],
    ]);
    const reloaded = credentialReducer(typed, {
      type: 'reloaded',
      provider: stored({ method: 'private_key_jwt', date: D }),
    });
    const view = credentialView(reloaded, 'entra');
    expect(view).toMatchObject({ secret: 'n', pendingSecret: true });
    expect(credentialPayload(reloaded, 'entra')).toEqual({
      client_secret: 'n',
      client_secret_expires_at: null,
    });
    const untouched = credentialReducer(run(stored({ date: D }), []), {
      type: 'reloaded',
      provider: stored({ date: X }),
    });
    expect(credentialView(untouched, 'entra').secretExpiry).toBe(X);
  });
});

describe('every ordering of credential edits, saves and reloads', () => {
  // Each operation acts on the form state and on an independent record of
  // what the administrator did (`log`), from which the invariants are judged
  // without consulting the code under test.
  const STEPS = [
    'type',
    'erase',
    'dateX',
    'dateD',
    'clear',
    'radioSecret',
    'radioCert',
    'save',
    'reload',
  ];
  const DEPTH = 6;

  const fail = (path, message) => {
    throw new Error(`${message} after [${path.join(', ')}]`);
  };

  // log: { typed: what the field holds, typeRunStart, dateOps: [{value, at}],
  // reset at each save }
  const check = (path, server, state, log) => {
    const before = server.client_secret_expires_at ?? '';
    const payload = credentialPayload(state, 'entra');
    const view = credentialView(state, 'entra');
    const answer = serverPatch(server, payload);
    const after = answer.client_secret_expires_at ?? '';

    // A typed secret is never dropped, and never sent unseen.
    if (log.typed !== '' && payload.client_secret !== log.typed) {
      fail(path, `the typed secret ${log.typed} was not sent`);
    }
    if (log.typed === '' && Object.hasOwn(payload, 'client_secret')) {
      fail(path, 'a secret was sent that the administrator did not type');
    }
    if (Object.hasOwn(payload, 'client_secret')) {
      const shown =
        view.credential === 'secret'
          ? view.secret === payload.client_secret
          : view.pendingSecret;
      if (!shown) fail(path, 'a secret was sent while the screen hid it');
    }
    // The stored date is not changed by a save with no new secret and no
    // date edit.
    if (
      !Object.hasOwn(payload, 'client_secret') &&
      log.dateOps.length === 0 &&
      after !== before
    ) {
      fail(path, `the stored date ${before} became ${after} with no edit`);
    }
    // A new secret never carries the old date unless it was set after typing.
    if (
      Object.hasOwn(payload, 'client_secret') &&
      before !== '' &&
      after === before &&
      !log.dateOps.some((o) => o.value === before && o.at > log.typeRunStart)
    ) {
      fail(path, `the new secret inherited the old date ${before}`);
    }
    // What is shown is what is saved.
    if (view.secretExpiry !== after) {
      fail(path, `the form showed ${view.secretExpiry} but saved ${after}`);
    }
    return answer;
  };

  const afterSaveShowsServer = (path, answer, state) => {
    const view = credentialView(state, 'entra');
    const expected = {
      credential:
        answer.client_auth_method === 'private_key_jwt'
          ? 'certificate'
          : 'secret',
      secret: '',
      secretExpiry: answer.client_secret_expires_at ?? '',
      pendingSecret: false,
      pendingDate: false,
    };
    for (const [k, v] of Object.entries(expected)) {
      if (view[k] !== v) {
        fail(path, `after the save the form showed ${k}=${view[k]}, not ${v}`);
      }
    }
  };

  const walk = (path, server, state, log, depth, counter) => {
    counter.n += 1;
    if (depth === DEPTH) {
      check([...path, 'final save'], server, state, log);
      return;
    }
    for (const step of STEPS) {
      const p = [...path, step];
      const at = path.length;
      let s = state;
      let srv = server;
      let l = log;
      switch (step) {
        case 'type': {
          const typed = `${log.typed}k`;
          s = credentialReducer(state, OPS.type(typed));
          l = {
            ...log,
            typed,
            typeRunStart: log.typed === '' ? at : log.typeRunStart,
          };
          break;
        }
        case 'erase':
          s = credentialReducer(state, OPS.erase());
          l = { ...log, typed: '', typeRunStart: null };
          break;
        case 'dateX':
        case 'dateD':
        case 'clear': {
          const value = { dateX: X, dateD: D, clear: '' }[step];
          s = credentialReducer(state, OPS.date(value));
          l = { ...log, dateOps: [...log.dateOps, { value, at }] };
          break;
        }
        case 'radioSecret':
          s = credentialReducer(state, OPS.radio('secret'));
          break;
        case 'radioCert':
          s = credentialReducer(state, OPS.radio('certificate'));
          break;
        case 'save': {
          srv = check(p, server, state, log);
          s = credentialReducer(state, { type: 'saved', provider: srv });
          afterSaveShowsServer(p, srv, s);
          l = { typed: '', typeRunStart: null, dateOps: [] };
          break;
        }
        case 'reload': {
          s = credentialReducer(state, { type: 'reloaded', provider: server });
          if (log.typed === '' && log.dateOps.length === 0) {
            const shown = credentialView(s, 'entra').secretExpiry;
            if (shown !== (server.client_secret_expires_at ?? '')) {
              fail(p, `an untouched date showed ${shown} after a reload`);
            }
          }
          break;
        }
        default:
          break;
      }
      walk(p, srv, s, l, depth + 1, counter);
    }
  };

  it.each([
    ['client_secret_post', null],
    ['client_secret_post', D],
    ['private_key_jwt', null],
    ['private_key_jwt', D],
  ])(
    'stored %s with date %s: every sequence of 6 steps keeps the invariants',
    (method, date) => {
      const counter = { n: 0 };
      walk(
        [],
        stored({ method, date }),
        initialCredentialState(stored({ method, date })),
        { typed: '', typeRunStart: null, dateOps: [] },
        0,
        counter
      );
      // 9 steps to depth 6: 1 + 9 + ... + 9^6 states visited.
      expect(counter.n).toBe((9 ** 7 - 1) / 8);
    }
  );
});
