"""Every ORM read reachable from the relay, and exactly why each is here.

An empty allowlist is the target and is NOT the gate (spec line 1659).
A non-empty, comment-cited one passes: the alternative is deleting reads
this PR is not scoped to remove, which is how a guard turns an open
question into a settled-looking answer.

TWO GRANULARITIES, and the reason is in plan 2b-3's Ruling R3.

  SITES  -- scope 1, per line, inside apps/proxy/live_proxy/**. Precise;
            the ratchet bites on any new one, in either direction.
  EDGES  -- scope 2, per in-process import edge out of the package. One
            entry clears a symbol's whole reachable subtree, because
            per-line would put dozens of lines of a control-plane module
            here to say one thing. The `hits` count is the ratchet in
            its place: it moves only when ORM usage inside the subtree
            changes. Because `scan_edge` depends only on (module, name)
            and not on who imports it, the SAME symbol imported by
            several relay files produces several entries with the SAME
            `hits` count -- one per importer, per Ruling R3's "one entry
            per (importing file, module, symbol)".

WHAT EDGE GRANULARITY TOLERATES, said plainly: an ORM read added inside
an already-cleared subtree is caught by the count but not named. The
count says "look"; it does not say where.

`closed_by` is load-bearing beyond this PR. Spec line 1769 makes 2c-1's
precondition "for every entry, name either the contract field that
closes it or the written reason the Go relay never asks that question".
That is this field, and AllowlistShapeTests asserts it is non-empty.

MEASURED AT 04841a47 (2b-2's squash-merge landed on main before this
branch was cut, and moved several of the sites and edges the plan this
file implements was written against at 93900a6f -- see plan 2b-3's own
task 2, which anticipates exactly this and requires re-measurement
rather than transcription). Every count and line number below was read
from `python -c "... zero_orm_scan ..."` against this tree, not copied
from the plan. Where a number differs from the plan's own worked
example, this measurement is the one that governs.
"""

from collections import namedtuple

Site = namedtuple("Site", "path lineno pr reason closed_by")
EdgeEntry = namedtuple("EdgeEntry", "importer module name hits pr reason closed_by")
Signature = namedtuple(
    "Signature",
    "name sql_fragment table_model exercised_by reason params_fragment",
    # params_fragment defaults to "" (always matches): only the
    # CoreSettings group-key lookups below need it. Django parameterizes
    # the settings `key` string, so two different groups (e.g.
    # "proxy_settings" and "stream_settings") produce byte-identical SQL
    # TEXT -- "WHERE key = %s" either way -- and an `sql_fragment` alone
    # cannot tell them apart. Found the hard way: an injected read of a
    # THIRD, unrelated group key matched the "stream_settings" signature
    # by SQL shape alone and the break-check that was supposed to catch
    # it passed silently. `params_fragment`, checked against
    # `repr(query.params)`, is what makes the allowlist name the actual
    # key rather than "any lookup shaped like this one".
    defaults=("",),
)

SITES = (
    Site(
        path="apps/proxy/live_proxy/channel_status.py",
        lineno=74,
        pr="2b-3",
        reason=(
            "The stream_name fallback, read when the metadata hash carries a "
            "stream_id and no name. NOT deleted: every name write in the tree "
            "is guarded on a value that arrives from Django "
            "(services/channel_service.py:303-308, :364-369, :931-939; "
            "input/manager.py:2175-2178), and url_utils.py:31-42's "
            "tune_extras exists to degrade all four names to None when the "
            "answer comes from a Django that predates 2b-1. The relay and the "
            "control plane are separately deployable, so version skew is a "
            "supported state; 2b-1's author recorded exactly this at "
            "views.py:553-566. Under a same-version deployment the branch is "
            "dead, which is a property of a deployment and not something a "
            "guard can assert. Parity-matrix row 18, plan 2b-3 Ruling R7."
        ),
        closed_by=(
            "Nothing on the contract closes it, and nothing needs to. Row 18's "
            "answer is that ABSENCE is the contract: when Redis has no name, "
            "the key is absent from the status payload entirely -- not null, "
            "not '' -- which RelayChannelDetailSerializer already declares "
            "(relay_serializers.py:111, :113, both required=False). The ORM "
            "fallback is best-effort enrichment on top of that. The Go relay, "
            "having no database, always omits the key, which is inside the "
            "contract rather than a divergence from it. This Python branch is "
            "deleted wholesale in migration/phase2d-delete-live-proxy."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/channel_status.py",
        lineno=106,
        pr="2b-3",
        reason=(
            "The m3u_profile_name fallback, same shape and same decision as "
            ":74. Its carriers are required=False on "
            "RelayAdvanceRequestSerializer (:202-211) and absent from "
            "input/manager.py:2016-2019's _CACHED_ALTERNATE_REQUIRED_FIELDS, "
            "so a degraded failover can write M3U_PROFILE from a stale cache "
            "entry with no name beside it. The spec and the parity matrix "
            "both cited :92 for this read at 93900a6f; the current tree "
            "(2b-1's seven-line comment above it) has it at :106 (plan 2b-3 "
            "Ruling R10)."
        ),
        closed_by="As :74 -- absence is the contract. Row 18.",
    ),
    Site(
        path="apps/proxy/live_proxy/config_helper.py",
        lineno=50,
        pr="2b-1",
        reason=(
            "TSConfig.get_proxy_settings() -> CoreSettings.get_proxy_settings "
            "(core/models.py) through apps/proxy/config.py's 10-second "
            "process-local cache. Issue #253 item 3: 2b-1 put proxy_settings "
            "on next-source's response and deliberately did not wire "
            "StreamManager to prefer it, so the read is still live at the end "
            "of 2b. Same precedent as 2b-1's own 'nothing in the Python relay "
            "consumes this yet, deliberately'."
        ),
        closed_by=(
            "proxy_settings on next-source's response (2b-1). The Go relay "
            "takes channel-start values from the tune answer and never reads "
            "CoreSettings, which also collapses #232's 10-second staleness "
            "window to zero for every value that matters at channel start."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=132,
        pr="2b-2",
        reason=(
            "_resolve_output_format's trusted branch: "
            "`decision.output_format or CoreSettings.get_default_output_"
            "format()`. Reached only when nginx authorized the tune (Ruling "
            "D-shape) but the hop left decision.output_format falsy -- since "
            "2b-2 the hop always resolves and sets X-Relay-Output-Format on "
            "a live tune, so this side of the `or` is dead on every "
            "nginx-authorized path today and survives as the defensive "
            "fallback for a relay talking to a pre-2b-2 hop."
        ),
        closed_by=(
            "X-Relay-Output-Format, the sixth relay header 2b-2 added. The Go "
            "relay reads the header and never resolves a default itself; the "
            "dev/inline fallback resolves it in Django, at the authorize hop "
            "(apps/proxy/authorize.py's resolve_output_format, see the "
            "matching EDGE entry below)."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=152,
        pr="2b-2",
        reason=(
            "OutputProfile.objects.filter(id=..., is_active=True) so "
            "build_command() can be called. Left in place deliberately by "
            "2b-2; its Ruling R3 is transcribed in closed_by below rather "
            "than paraphrased, because spec line 1769 makes 2c-1 restate it "
            "and it is written once."
        ),
        closed_by=(
            # Verbatim from docs/superpowers/plans/
            # 2026-09-12-phase2-2b2-output-profile-and-user.md:104. Do not
            # reword: 2c-1's precondition restates this paragraph. (Line
            # numbers in the quoted text are as that plan wrote them; the
            # site this entry allowlists is *this* tree's views.py:152.)
            "views.py:152 stays. The contract field that closes it is "
            "output_profiles on next-source's response: the Go relay caches "
            "the map at tune and serves every later client from memory. "
            "Python cannot, because _output_profile_for runs per client "
            "(views.py:605 owner-init, :712 everything else, at 93900a6f -- "
            "this tree's current equivalents are views.py's owner-init and "
            "follower branches of stream_ts) while next-source runs per "
            "channel, and closing it in Python would need a cache whose "
            "staleness semantics nothing has specified."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=444,
        pr="2b-3",
        reason=(
            "channel.get_stream_profile() -- issue #253's headline finding, "
            "and the shape that made this scanner an AST scan rather than a "
            "grep. apps/channels/models.py falls through to "
            "StreamProfile.objects.get and touches an FK accessor first, so "
            "it is worth one to several queries, not one. #253 cited :430 at "
            "ef3d3145 and the 2b-2 plan's own worked example cited :434 at "
            "93900a6f; 2b-2's changes moved it again, to :444."
        ),
        closed_by=(
            "stream_profile on next-source's response -- already on the "
            "contract since Phase 1 PR 6 (control_plane.next_source's Source "
            "dict, next_source.py's resolve_source result). The Go relay "
            "reads the profile it was handed at tune and never resolves one."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=785,
        pr="2b-3",
        reason="channel.get_stream_profile(), as views.py:444. #253 cites :741 at ef3d3145.",
        closed_by="stream_profile on next-source's response, as views.py:444.",
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=788,
        pr="2b-3",
        reason="channel.get_stream_profile(), as views.py:444. #253 cites :744 at ef3d3145.",
        closed_by="stream_profile on next-source's response, as views.py:444.",
    ),
    # --- cleared by inspection: a model method that issues no query ---
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=766,
        pr="2b-3",
        reason=(
            "resolved_output_profile.build_command(). A model METHOD, so the "
            "scanner flags it, but core/models.py's OutputProfile.build_"
            "command is `[self.command] + shlex_split(self.parameters)` -- "
            "two already-loaded fields, no query, no descriptor. Kept on the "
            "list rather than stoplisted: build_command is also "
            "StreamProfile's, and a stoplist entry would blind the scanner "
            "to both on every file."
        ),
        closed_by=(
            "Nothing to close -- no query. The Go relay builds the same argv "
            "from output_profiles on next-source's response (2b-2 Ruling R3)."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=791,
        pr="2b-3",
        reason="stream_profile.build_command(...); pure, as views.py:766.",
        closed_by="Nothing to close -- no query.",
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=462,
        pr="2b-3",
        reason=(
            "stream_profile.is_redirect(). A model method on an object the "
            "caller already holds; core/models.py compares self.name against "
            "a constant. No query."
        ),
        closed_by="Nothing to close -- no query.",
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=468,
        pr="2b-3",
        reason="stream_profile.is_redirect(), as :462.",
        closed_by="Nothing to close -- no query.",
    ),
)

EDGES = (
    EdgeEntry(
        importer="apps/proxy/live_proxy/views.py",
        module="apps.proxy.next_source",
        name="resolve_source",
        hits=36,
        pr="2b-3",
        reason=(
            "SETTLED HERE, and issue #253 left it open: resolve_source is NOT "
            "dead in the relay. It is called in-process at views.py:942 "
            "(change_stream) and views.py:1291 (next_stream) -- the operator "
            "switch paths, both relay-served. Its reachable subtree is 36 "
            "ORM sites (measured at 04841a47; the 2b-3 plan's own worked "
            "example measured 34 at 93900a6f) spanning "
            "get_stream_info_for_switch's get_object_or_404 chain, "
            "resolve_initial_source, _source_from_info's "
            "StreamProfile.objects.get, _resolve_alternates, _commit, "
            "_with_proxy_settings and _with_output_profiles. #253's "
            "'looks like API-process or dead code; they were read, not "
            "executed' is withdrawn."
        ),
        closed_by=(
            "POST /api/relay/channels/<id>/next-source with target_stream_id "
            "-- already on the contract (apps/proxy/control_plane.py, and "
            "next_source.resolve_source's own target_stream_id parameter). "
            "The Go relay makes the operator switch a control-plane round "
            "trip instead of an import; 2c-8 owns the route."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/services/channel_service.py",
        module="apps.proxy.next_source",
        name="resolve_source",
        hits=36,
        pr="2b-3",
        reason=(
            "The same symbol as the views.py edge above, and a SEPARATE "
            "entry because Ruling R3 allowlists per (importer, module, "
            "name): channel_service.py:415 calls resolve_source directly "
            "for the pub/sub-driven operator switch (server.py's switch "
            "listener), a second in-process call site #253 did not "
            "separately record. Same 36-hit subtree as the views.py edge; "
            "the count is identical by construction, since scan_edge "
            "depends only on the target module and symbol, never on who "
            "imports it."
        ),
        closed_by="As the views.py edge above -- POST .../next-source with target_stream_id.",
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/url_utils.py",
        module="apps.proxy.next_source",
        name="get_stream_object",
        hits=3,
        pr="Phase 1 PR 6",
        reason=(
            "Two get_object_or_404 calls and a select_related. Executes in "
            "the relay at views.py's channel-identifier resolution and at "
            "input/manager.py:774-ish, and at authorize.py on the inline "
            "authorize path. Issue #253 item 2."
        ),
        closed_by=(
            "next-source's identifier resolution, which 2b-1 extended to "
            "accept a stream_hash as well as a channel uuid (parity row 16). "
            "The Go relay sends whatever identifier arrived in the URL and "
            "Django resolves it, which is what get_stream_object already does."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/client_manager.py",
        module="apps.proxy.config",
        name="TSConfig",
        hits=5,
        pr="2b-1",
        reason=(
            "TSConfig (apps/proxy/config.py) is a first-party class the "
            "relay imports for its buffer/health/client-tracking constants. "
            "Five of ITS OWN classmethods -- get_channel_shutdown_delay, "
            "get_buffering_timeout, get_buffering_speed, "
            "get_channel_init_grace_period, get_channel_client_wait_period, "
            "inherited from BaseConfig -- each call `cls.get_proxy_settings"
            "()`, whose name matches CoreSettings.get_proxy_settings in the "
            "model-method set (the scanner is name-based per Ruling R2, so "
            "it flags these without needing to trace that TSConfig's own "
            "get_proxy_settings really does reach CoreSettings). This is "
            "one of five entries for the same symbol -- Ruling R3 allowlists "
            "per importer, and TSConfig is imported into five relay files."
        ),
        closed_by=(
            "proxy_settings on next-source's response (2b-1), same as "
            "config_helper.py:50's SITE entry above. The Go relay takes "
            "channel-start values from the tune answer and never reads "
            "CoreSettings."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/config_helper.py",
        module="apps.proxy.config",
        name="TSConfig",
        hits=5,
        pr="2b-1",
        reason="As the client_manager.py entry above -- same symbol, same 5-hit subtree, a second importer.",
        closed_by="As the client_manager.py entry above.",
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/input/manager.py",
        module="apps.proxy.config",
        name="TSConfig",
        hits=5,
        pr="2b-1",
        reason="As the client_manager.py entry above -- same symbol, same 5-hit subtree, a third importer.",
        closed_by="As the client_manager.py entry above.",
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/output/ts/generator.py",
        module="apps.proxy.config",
        name="TSConfig",
        hits=5,
        pr="2b-1",
        reason="As the client_manager.py entry above -- same symbol, same 5-hit subtree, a fourth importer.",
        closed_by="As the client_manager.py entry above.",
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/server.py",
        module="apps.proxy.config",
        name="TSConfig",
        hits=5,
        pr="2b-1",
        reason="As the client_manager.py entry above -- same symbol, same 5-hit subtree, a fifth importer.",
        closed_by="As the client_manager.py entry above.",
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/views.py",
        module="apps.proxy.authorize",
        name="resolve_output_format",
        hits=1,
        pr="2b-2",
        reason=(
            "The inline/untrusted counterpart to views.py:132's SITE: when "
            "nothing else supplies a format (no ?output_format=, no user "
            "custom_properties), resolve_output_format's own last line falls "
            "back to CoreSettings.get_default_output_format() -- one ORM "
            "hit, inside apps/proxy/authorize.py, a module the relay imports "
            "for the shared authorize rule (2b-2's 'the hop and the inline "
            "path cannot drift')."
        ),
        closed_by=(
            "X-Relay-Output-Format on a trusted tune (2b-2); the untrusted/"
            "inline path is the one production shape that still resolves "
            "this in Python, and it is what "
            "test_an_untrusted_tune_executes_a_recorded_set_and_no_other "
            "(Task 4 Step 5b) characterizes rather than gates."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/views.py",
        module="apps.proxy.authorize",
        name="resolve_output_profile",
        hits=2,
        pr="2b-2",
        reason=(
            "The inline/untrusted counterpart to views.py:152's SITE: "
            "?output_profile= then the user's custom_properties, two "
            "OutputProfile.objects.get(...) calls guarding two independent "
            "resolution attempts. Reached only when the tune was not "
            "nginx-authorized (decision.trusted is False)."
        ),
        closed_by=(
            "X-Relay-Output on a trusted tune (2b-2) -- the hop resolves "
            "?output_profile=/custom_properties once and puts the id on the "
            "header, so a trusted tune never calls this. views.py:152's own "
            "SITE (R9) is the separate reason the ROW still needs re-reading "
            "in Python even on a trusted tune -- OutputProfile.build_command "
            "is model behaviour a header cannot carry."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/views.py",
        module="apps.proxy.authorize_views",
        name="resolve_authorization",
        hits=1,
        pr="Phase 1 PR 5",
        reason=(
            "result_from_headers' User.objects.filter(id=int(user_id))."
            "first() -- reached from resolve_authorization, imported for the "
            "inline (non-nginx) authorize path. The static scanner flags it "
            "and the runtime check clears it, and the reason is a SURFACE "
            "SPLIT, not laziness: the query sits in the `else` arm of "
            "`if surface in (SURFACE_LIVE, SURFACE_LIVE_XC):`, so a live "
            "tune never enters it, while /proxy/vod/, /proxy/catchup/ and "
            "/streaming/timeshift.php keep today's code verbatim."
        ),
        closed_by=(
            "The surface split plus X-Relay-User (2b-2), NOT 'the field is "
            "lazily resolved'. An earlier draft proposed a lazy User proxy "
            "and it was withdrawn at 71cd8d31: `is` cannot be overloaded, "
            "and eleven of the field's fourteen consumers test identity, so "
            "a stand-in object would be permanently wrong for all eleven -- "
            "most sharply at vod_proxy/views.py:783, where `if user is "
            "None` is a recovery path a non-None stand-in would silently "
            "disable. Under the split, only a change to the surface "
            "constant or the branch resurrects the query for a live tune; "
            "under laziness, any consumer touching the field would have."
        ),
    ),
)

# Measured by running RuntimeGuardTests against this tree with a
# temporary catch-all signature and a debug print of every captured
# relay query's SQL text (plan Task 4 Step 3) -- these are the literal
# fragments that fired, typed by hand, never generated from the capture.
SQL_SIGNATURES = (
    Signature(
        name="channel_by_uuid",
        sql_fragment='FROM "dispatcharr_channels_channel" WHERE "dispatcharr_channels_channel"."uuid" = %s',
        table_model="dispatcharr_channels.Channel",
        exercised_by="owner tune, follower tune",
        reason=(
            "get_stream_object(channel_id), called directly at the top of "
            "stream_ts (views.py) and again inside StreamManager "
            "(input/manager.py, via the same in-package url_utils "
            "re-export) -- the EDGE at "
            "url_utils.py <- apps.proxy.next_source.get_stream_object."
        ),
    ),
    Signature(
        name="channel_override_fk_accessor",
        sql_fragment='FROM "dispatcharr_channels_channeloverride" WHERE "dispatcharr_channels_channeloverride"."channel_id" = %s',
        table_model="dispatcharr_channels.ChannelOverride",
        exercised_by="owner tune",
        reason=(
            "The FK accessor channel.get_stream_profile() touches before "
            "falling through to StreamProfile.objects.get -- issue #253's "
            "'worth one to several queries, not one'. SITES views.py:444 "
            "and input/manager.py:788."
        ),
    ),
    Signature(
        name="stream_profile_by_id",
        sql_fragment='FROM "core_streamprofile" WHERE "core_streamprofile"."id" = %s',
        table_model="core.StreamProfile",
        exercised_by="owner tune",
        reason="StreamProfile.objects.get inside channel.get_stream_profile(). SITES views.py:444 and input/manager.py:785/:788.",
    ),
    Signature(
        name="output_profile_for_this_client",
        sql_fragment='FROM "core_outputprofile" WHERE ("core_outputprofile"."id" = %s AND "core_outputprofile"."is_active")',
        table_model="core.OutputProfile",
        exercised_by="owner tune, follower tune",
        # The owner-init call site and the everything-else call site are
        # the SAME function body (views.py:151-154, the SITE at :152) --
        # one signature covers both call frames, since a signature
        # matches by SQL text, not by which call site reached it. See
        # SITES, and 2b-2 Ruling R3 transcribed there.
        reason="views.py:152 -- OutputProfile.objects.filter(id=..., is_active=True).",
    ),
    Signature(
        name="stream_name_fallback",
        sql_fragment='FROM "dispatcharr_channels_stream" WHERE "dispatcharr_channels_stream"."id" = %s',
        table_model="dispatcharr_channels.Stream",
        exercised_by="status read, names stripped",
        reason="channel_status.py:74's Stream.objects.filter(id=stream_id).first() -- fires only once STREAM_NAME is absent from the hash. Row 18.",
    ),
    Signature(
        name="m3u_profile_name_fallback",
        sql_fragment='FROM "m3u_m3uaccountprofile" WHERE "m3u_m3uaccountprofile"."id" = %s',
        table_model="m3u.M3UAccountProfile",
        exercised_by="status read, names stripped",
        reason="channel_status.py:106's M3UAccountProfile.objects.filter(id=m3u_profile_id).first() -- fires only once M3U_PROFILE_NAME is absent from the hash. Row 18.",
    ),
    Signature(
        name="proxy_settings_group",
        sql_fragment='FROM "core_coresettings" WHERE "core_coresettings"."key" = %s',
        # The `key` value is a bound param, not SQL text, so two
        # different settings groups are byte-identical SQL and
        # params_fragment is what tells them apart (see Signature's own
        # docstring above -- found via a break-check that passed when it
        # should not have).
        params_fragment="'proxy_settings'",
        table_model="core.CoreSettings",
        # NOT marked exercised: config_helper.py:50's TSConfig.get_proxy_
        # settings sits behind a 10-second process-local cache whose
        # warm/cold state depends on what ran earlier in the same test
        # process -- this programme has already measured flapping regions
        # from exactly this kind of state and Task 4 Step 3 says mark
        # exercised_by only where a drive makes the read deterministic.
        # Present so a cache-cold run does not fail with "no allowlisted
        # signature" for an already-allowlisted SITE (config_helper.py:50).
        exercised_by="",
        reason=(
            "config_helper.py:50's TSConfig.get_proxy_settings() reads "
            "this group through a 10-second process-local cache; whether "
            "it fires on a given run depends on cache state this guard "
            "does not control, so it is recorded but not required. "
            "views.py:132's SITE reads a DIFFERENT group (stream_settings, "
            "the inline_default_output_format signature below) and is "
            "unreached by every drive here regardless -- see its own "
            "reason in SITES."
        ),
    ),
)

# Task 4 Step 5b. Characterization, NOT policy: it records what the
# inline (untrusted) authorize path does -- in production, nginx runs
# that hop in the API process behind auth_request, never in the relay --
# so shrinking this list is not a goal. Measured the same way as
# SQL_SIGNATURES, against a real untrusted tune.
INLINE_AUTHORIZE_SIGNATURES = (
    Signature(
        name="inline_network_access_settings",
        sql_fragment='FROM "core_coresettings" WHERE "core_coresettings"."key" = %s',
        params_fragment="'network_access'",
        table_model="core.CoreSettings",
        exercised_by="untrusted tune",
        # Found by a break-check, not by the first measurement: an
        # earlier draft of this list omitted it because the first
        # measurement ran with this group's Redis-backed cache already
        # warm from an app-startup fetch, and the query simply did not
        # fire that time. Task 4 Step 5b's own break-check (add a read to
        # the inline path, expect `unrecorded` to redden) caught it on a
        # freshly flushed Redis -- the drive is not "the only thing that
        # reaches CoreSettings," it reaches it TWICE, on two different
        # groups, and only one was in the first draft.
        reason=(
            "dispatcharr/utils.py's network_access_allowed(), called from "
            "authorize_stream() (apps/proxy/authorize.py) before the ACL "
            "check, reads the 'network_access' settings group. Runs on "
            "EVERY authorize_stream call, anonymous or not -- it is not "
            "conditioned on a resolved principal the way "
            "check_user_stream_limits() is."
        ),
    ),
    Signature(
        name="inline_channel_by_uuid",
        sql_fragment='FROM "dispatcharr_channels_channel" WHERE "dispatcharr_channels_channel"."uuid" = %s',
        table_model="dispatcharr_channels.Channel",
        exercised_by="untrusted tune",
        reason=(
            "get_stream_object, twice: once inside resolve_authorization's "
            "inline branch (views.py, the authorize_stream call resolves "
            "the channel to apply the ACL) and once again at stream_ts's "
            "own get_stream_object(channel_id) call -- the hop's job, "
            "duplicated in-process because there is no hop here."
        ),
    ),
    Signature(
        name="inline_channel_override_fk_accessor",
        sql_fragment='FROM "dispatcharr_channels_channeloverride" WHERE "dispatcharr_channels_channeloverride"."channel_id" = %s',
        table_model="dispatcharr_channels.ChannelOverride",
        exercised_by="untrusted tune",
        reason="channel.get_stream_profile()'s FK accessor, same as SQL_SIGNATURES' entry, reached on the inline path too.",
    ),
    Signature(
        name="inline_stream_profile_by_id",
        sql_fragment='FROM "core_streamprofile" WHERE "core_streamprofile"."id" = %s',
        table_model="core.StreamProfile",
        exercised_by="untrusted tune",
        reason="StreamProfile.objects.get inside channel.get_stream_profile(), same as SQL_SIGNATURES' entry.",
    ),
    Signature(
        name="inline_default_output_format",
        sql_fragment='FROM "core_coresettings" WHERE "core_coresettings"."key" = %s',
        params_fragment="'stream_settings'",
        table_model="core.CoreSettings",
        exercised_by="untrusted tune",
        reason=(
            "apps/proxy/authorize.py's resolve_output_format, its own "
            "last-resort CoreSettings.get_default_output_format() call -- "
            "reached because resolve_authorization's inline branch calls "
            "authorize_stream() rather than result_from_headers(), so "
            "decision.trusted is False and _resolve_output_format takes "
            "the `return resolve_output_format(...)` branch. NOT "
            "views.py:132's SITE, which needs decision.trusted True with "
            "decision.output_format falsy at once -- unreached by every "
            "drive here, trusted or not (2b-2 always sets X-Relay-Output-"
            "Format on a trusted tune)."
        ),
    ),
)
