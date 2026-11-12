# Recovering sign-in when single sign-on fails

This page is for an operator with shell access to the Mino container. Use it when password
sign-in is turned off and nobody can sign in through single sign-on (SSO): the provider's
credential expired, the identity provider is down, the app registration was deleted, or a
role mapping stopped matching.

Nothing on this page is reachable from the web. Turning password sign-in back on needs the
container, never a browser.

## How the commands are run

Run every command through a login shell, exactly as written:

```text
docker exec [-it] <container> su - dispatch -c 'cd /app && python manage.py <command>'
```

Running `python manage.py` straight from `docker exec`, without `su -`, does not work. The
server reads its secret key from an environment variable that the entrypoint exports only to
login shells, so a command run without `su -` cannot read the settings it needs.
`su - dispatch` also runs the command as the application user rather than root.

Replace `<container>` with the container's name. `dispatch` is the default database user; if
your deployment sets `POSTGRES_USER`, use that name instead. Commands that prompt for input
(`changepassword`, `createsuperuser`) need `-it`.

Each command first prints the server's start-up log lines and warnings. The expected output
shown below is the command's own lines, which come last.

## The procedure

### 1. Turn password sign-in back on

Either way works. The first needs no restart.

```bash
docker exec <container> su - dispatch -c 'cd /app && python manage.py password_login --enable'
```

Expected output:

```text
Password login enabled.
Active admins with a usable password: 1
```

Or set `MINO_PASSWORD_LOGIN_FORCE=1` in the container's environment and restart it. While
it is set, password sign-in is on whatever the stored setting says, the login page and the
Single sign-on settings show a banner saying so, and every password sign-in is recorded with
`break_glass` in the event log. Any other value than `1` is ignored and logged as a warning.

### 2. Check whether an admin can sign in with a password

Read the last line `--enable` printed. If it reports at least one active admin with a usable
password, sign in as that admin and go to step 4. To print it again, with the stored value,
the override and every enabled provider's credential state:

```bash
docker exec <container> su - dispatch -c 'cd /app && python manage.py password_login --status'
```

Expected output, for an instance whose only provider's credential has expired and whose
admins were all created by single sign-on:

```text
Password login (stored): enabled
MINO_PASSWORD_LOGIN_FORCE: off
Password login now: enabled
Enabled providers: 1
  entra: credential expired, expired on 2026-11-01
Active admins with a usable password: 0
No admin can sign in with a password yet. Give one a password with `python manage.py changepassword <admin-username>`, or create a new admin with `python manage.py createsuperuser`. See docs/sso-recovery.md.
```

### 3. Give an admin a password, if none has one

Admins created by single sign-on have no password. Either set one on an existing admin:

```bash
docker exec -it <container> su - dispatch -c 'cd /app && python manage.py changepassword <admin-username>'
```

Expected output, after you type the new password twice:

```text
Changing password for user '<admin-username>'
Password changed successfully for user '<admin-username>'
```

or create a new local admin:

```bash
docker exec -it <container> su - dispatch -c 'cd /app && python manage.py createsuperuser'
```

which prompts for a username, an email address and a password, and ends with
`Superuser created successfully.` This second form is also the recovery when no admin exists
at all, because the first-run setup page stays closed once a provider exists.

### 4. Sign in with the password and repair the provider

Sign in on the login page with the password. In Settings, Single sign-on, fix what broke:

- An expired or replaced client secret: create a new secret at the identity provider and
  save it with its expiry date.
- An expired certificate: generate a new certificate, upload it to the identity provider,
  and activate it.

Then run the provider's **Test**.

### 5. Turn password sign-in off again

Sign out, sign in through single sign-on, and switch password sign-in off from that session
in Settings, Single sign-on. The switch accepts only a session that single sign-on signed in
as Admin through a provider that is enabled now. If you set `MINO_PASSWORD_LOGIN_FORCE`,
remove it and restart the container.

The command line can also turn it off, provided at least one provider is enabled:

```bash
docker exec <container> su - dispatch -c 'cd /app && python manage.py password_login --disable'
```

Expected output: `Password login disabled.` With no enabled provider it is refused, naming
`last_enabled_provider`. `--force` turns it off anyway, which leaves nobody able to sign in
until a provider is enabled; it is refused outright on a SQLite database.

### 6. Decide what to do with the recovery account

An admin given a password in step 3 keeps it. Delete the account from the Users page, or keep
it deliberately as a local fallback.

## What still works while password sign-in is off

- API keys (`X-API-Key`) keep working.
- An access token already issued keeps working until it expires, at most 30 minutes. A
  refresh token issued by a password sign-in stops refreshing at once; one issued by single
  sign-on keeps refreshing while its provider stays enabled.
- A browser session on the Django admin site stops working, and its login page refuses.
  Such a session also stops authorizing streams.
- Stream and M3U URLs authorize as before.

## Stopping a user at once

When an identity provider removes someone, their next sign-in is refused, but a token pair
already issued keeps working until its refresh token expires. To stop it now, deactivate the
user on the Users page, or, when no admin can sign in:

```bash
docker exec <container> su - dispatch -c 'cd /app && python manage.py shell -c "from apps.accounts.models import User; print(User.objects.filter(username=\"<name>\").update(is_active=False))"'
```

It prints `1` when the user existed and `0` when it did not.

Deactivation also stops the user's API key and Xtream (XC) credentials: Xtream logins,
playlists and every new stream request made with them are refused exactly as a wrong password
is. A stream already playing is not stopped; it continues until the player disconnects.

## Sign-in errors that point here

The login page shows a fixed message for each `sso_error` code. Two of them mean an operator
may need this page:

| Code | Meaning | What to do |
| --- | --- | --- |
| `client_auth_failed` | The identity provider rejected Mino's credential: it expired or was replaced. | Steps 1 to 5. |
| `provider_unavailable` | Sign-in could not reach or use the identity provider. | Run the provider's **Test**. If nobody can sign in, steps 1 to 5. |
