/**
 * A minimal ZIP writer, stored (uncompressed) entries only.
 *
 * Node has no zip container in its standard library, and the alternatives were
 * both worse: committing a binary archive fixes the plugin key (see the test),
 * and shelling out to `zip` adds a host dependency CI does not guarantee. A
 * stored-entry archive is ~60 lines of buffer arithmetic and Python's
 * `zipfile.ZipFile` — which is what `_install_plugin_from_zip` uses — reads
 * stored entries with no special handling.
 *
 * The plugin it builds is INERT BY CONSTRUCTION. Enabling a plugin causes
 * `PluginManager._load_plugin` to import its module into the uWSGI worker and
 * run it there, unsandboxed (CLAUDE.md, "Events and plugins"). This one
 * declares one settings field and a `run` that returns a constant — only
 * `run()` does anything at all, and only when a test calls it; importing and
 * enabling the plugin does nothing by itself.
 *
 * With `actions` supplied, `run` still does nothing until called, but an
 * `echo` action becomes available whose `run` derives its return value from
 * `params` (`{"echoed": params.get("token")}`), so a caller can prove its
 * parameters actually reached the plugin. `PluginManager.run_action`
 * (`apps/plugins/loader.py`) passes a `dict` return through verbatim and
 * wraps anything else as `{"status": "ok", "result": <value>}` before the
 * view nests it again under its own `"result"` key — returning a dict here
 * keeps the response one level shallower and the assertion readable.
 */

const CRC_TABLE: number[] = (() => {
  const table: number[] = [];
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

type Member = { path: string; data: Buffer };

function localHeader(member: Member, crc: number): Buffer {
  const name = Buffer.from(member.path, 'utf8');
  const head = Buffer.alloc(30);
  head.writeUInt32LE(0x04034b50, 0); // signature
  head.writeUInt16LE(20, 4); // version needed
  head.writeUInt16LE(0, 6); // flags
  head.writeUInt16LE(0, 8); // method: stored
  head.writeUInt16LE(0, 10); // mod time
  head.writeUInt16LE(0x21, 12); // mod date (1980-01-01; arbitrary and fixed — the DOS date's year field is an offset from 1980, and it's zero here)
  head.writeUInt32LE(crc, 14);
  head.writeUInt32LE(member.data.length, 18);
  head.writeUInt32LE(member.data.length, 22);
  head.writeUInt16LE(name.length, 26);
  head.writeUInt16LE(0, 28); // extra length
  return Buffer.concat([head, name]);
}

function centralHeader(member: Member, crc: number, offset: number): Buffer {
  const name = Buffer.from(member.path, 'utf8');
  const head = Buffer.alloc(46);
  head.writeUInt32LE(0x02014b50, 0);
  head.writeUInt16LE(20, 4); // version made by
  head.writeUInt16LE(20, 6); // version needed
  head.writeUInt16LE(0, 8);
  head.writeUInt16LE(0, 10); // stored
  head.writeUInt16LE(0, 12);
  head.writeUInt16LE(0x21, 14); // mod date, same value and rationale as the local header
  head.writeUInt32LE(crc, 16);
  head.writeUInt32LE(member.data.length, 20);
  head.writeUInt32LE(member.data.length, 24);
  head.writeUInt16LE(name.length, 28);
  head.writeUInt16LE(0, 30); // extra
  head.writeUInt16LE(0, 32); // comment
  head.writeUInt16LE(0, 34); // disk number
  head.writeUInt16LE(0, 36); // internal attrs
  head.writeUInt32LE(0, 38); // external attrs
  head.writeUInt32LE(offset, 42);
  return Buffer.concat([head, name]);
}

function zipOf(members: Member[]): Buffer {
  const local: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const member of members) {
    const crc = crc32(member.data);
    const head = localHeader(member, crc);
    local.push(head, member.data);
    central.push(centralHeader(member, crc, offset));
    offset += head.length + member.data.length;
  }
  const centralBuf = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(members.length, 8);
  end.writeUInt16LE(members.length, 10);
  end.writeUInt32LE(centralBuf.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...local, centralBuf, end]);
}

/**
 * The archive `_install_plugin_from_zip` expects: a directory containing
 * `plugin.py` (which is what makes it the chosen candidate) and a
 * `plugin.json` manifest, whose `fields` are what the Plugins page renders as
 * the settings form.
 */
export function buildPluginZip(opts: {
  key: string;
  name: string;
  /** Defaults to `[]` — omitting this produces a byte-identical archive to
   * before this parameter existed (see the zip-builder unit test). */
  actions?: { id: string; label: string }[];
}): Buffer {
  const actions = opts.actions ?? [];

  const manifest = JSON.stringify(
    {
      name: opts.name,
      version: '0.0.1',
      description: 'Inert fixture plugin for the Dispatcharr E2E suite.',
      author: 'dispatcharr-e2e',
      fields: [
        { id: 'note', label: 'Note', type: 'string', default: '' },
      ],
      actions,
    },
    null,
    2
  );

  const actionsLiteral =
    actions.length === 0
      ? '[]'
      : '[\n' +
        actions
          .map((a) => `        {"id": ${JSON.stringify(a.id)}, "label": ${JSON.stringify(a.label)}},`)
          .join('\n') +
        '\n    ]';

  // Only the `echo` action derives its result from `params`; anything else
  // (including no actions at all) keeps the original constant reply — this
  // is what keeps the `actions`-omitted archive byte-identical to before.
  const runBody =
    actions.length === 0
      ? ['        return {"status": "noop"}']
      : [
          '        if action == "echo":',
          '            return {"echoed": params.get("token")}',
          '        return {"status": "noop"}',
        ];

  const source = [
    'class Plugin:',
    `    name = ${JSON.stringify(opts.name)}`,
    '    version = "0.0.1"',
    '    description = "Inert fixture plugin for the Dispatcharr E2E suite."',
    '',
    '    fields = [',
    '        {"id": "note", "label": "Note", "type": "string", "default": ""},',
    '    ]',
    `    actions = ${actionsLiteral}`,
    '',
    '    def run(self, action, params, context):',
    ...runBody,
    '',
  ].join('\n');

  return zipOf([
    { path: `${opts.key}/plugin.json`, data: Buffer.from(manifest, 'utf8') },
    { path: `${opts.key}/plugin.py`, data: Buffer.from(source, 'utf8') },
  ]);
}
