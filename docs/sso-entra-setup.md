# Signing in with Microsoft Entra ID

This page walks an operator through registering Mino in Microsoft Entra ID (formerly Azure AD) so people can sign in with their work accounts. It matches the **Single sign-on** page in Settings, Security. Blade and field names are Microsoft's; the admin center changes over time, so treat them as a guide.

Before you start, set the **Public base URL** on that page to the address people use to reach Mino, for example `https://mino.example.com`. It must be `https` (plain `http` is accepted only for `localhost`).

## 1. Register the application

In the Entra admin center, open App registrations and create a registration.

- Supported account types: **Accounts in this organizational directory only** (single tenant).
- Note the **Directory (tenant) ID** and the **Application (client) ID**. You will paste both into Mino.

## 2. Add the redirect URI under the Web platform

In Mino, add a **Microsoft Entra ID** provider. The form shows the **Redirect URI** it computed from the public base URL and the slug, with a copy button.

In the app registration, open Authentication, add a platform, and choose **Web** (not Single-page application). Mino redeems the sign-in code on the server with a client credential, which a single-page registration does not allow. Paste the redirect URI. It must be `https` (`http` works only for `localhost`) and at most 256 characters; Mino warns when it is longer.

## 3. Require assignment

Enterprise applications, your application, Properties: set **Assignment required?** to **Yes**. Without it, anyone in your tenant can finish signing in at Entra and is turned away only by Mino's role mapping. Microsoft notes that an application requiring assignment needs tenant-wide admin consent, and that Global Administrators are not subject to the requirement.

## 4. Create app roles and assign them

App registrations, your application, App roles: create roles such as `Mino.Admin` and `Mino.User` (allowed member type: Users/Groups). Then Enterprise applications, Users and groups: assign people or groups to a role. Entra then sends the role names in the `roles` claim, which is the claim the Entra form maps by default. In the provider form, map each role value to a level (Streamer, Standard or Admin).

## 5. Only if you map on groups instead

Token configuration, Add groups claim, **Groups assigned to the application**. That option includes only groups assigned to the application and is recommended for large organizations because of the group limit in tokens. If a user belongs to too many groups, Entra sends no list and Mino refuses the sign-in (`groups_overage`); app roles avoid this, so prefer them.

## 6. Add the credential

Pick one in the provider form.

- **Certificate (recommended).** Choose Certificate, save the provider, then press **Generate certificate** and **Download certificate**. In Entra, Certificates & secrets, Certificates, **Upload certificate**. Back in Mino, press **Activate**. Activation checks that the certificate you activate is the one shown, and switches the provider to certificate sign-in. The private key never leaves Mino and can never be downloaded.
- **Client secret.** Certificates & secrets, **New client secret**. Copy the **Value** (not the Secret ID) into the provider form, and enter the expiry date Entra shows. A secret stops working on that date, and every sign-in then fails until it is replaced. Mino warns on the Settings page, and tells administrators when they sign in, before that happens.

The secret field is write-only: Mino never shows a stored secret. Leave the field empty to keep the stored one.

## 7. Test, then sign in

Press **Test** in the provider form. It fetches the provider's discovery document and signing keys and reports fixed problem messages. Enable the provider, open a private window, and sign in with the button on the login page. Only after that works should you consider anything that relies on SSO being the only way in.

## 8. Sovereign clouds and External ID

National-cloud tenants and Microsoft Entra External ID use the **generic OIDC** form, with the issuer and endpoints Microsoft documents for that cloud.

## What a sign-in error means

Mino shows a fixed message for each code; the code is in the address as `sso_error`.

| Code | Cause | What to do |
|---|---|---|
| `client_auth_failed` | The provider rejected Mino's credential: the secret or certificate is wrong, expired or was replaced. | Update the credential in Settings, Single sign-on. |
| `no_mapping` | The user has no role that the provider maps to a level. | Assign an app role (step 4) and map it in the form. |
| `groups_overage` | Too many groups for the token. | Map on app roles instead (step 4). |
| `last_admin` | The sign-in would remove the last active administrator. | Keep at least one administrator mapped, or fix the mapping. |
| `inactive` | The account is disabled in Mino. | An administrator re-activates it. |
| `link_conflict` | That provider account is already linked to a different user. | Unlink it from the other user first. |
| `id_token_invalid` | The sign-in token could not be verified. | Check the issuer and tenant ID; run Test. |
| `provider_mismatch` | The response did not match the provider the attempt started with. | Start again from the login page. |
| `state_invalid`, `binding_invalid` | The attempt expired, was reused, or started in a different browser. | Start again from the login page. |
| `token_exchange_failed` | The provider did not accept the sign-in code. | Check the credential and redirect URI. |
| `provider_unavailable` | Discovery or the provider could not be reached. | Run Test; check the network. |

Microsoft shows its own error page for problems before the user returns to Mino, and records codes in the sign-in log. Microsoft's reference is https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes.

| Entra code | Microsoft's description | What to do here |
|---|---|---|
| `AADSTS50011` | The reply address is missing, misconfigured, or doesn't match the app's reply addresses | Make the registered redirect URI identical to the one the form shows. Check the public base URL and slug. |
| `AADSTS900971` | No reply address provided | Add the redirect URI under the Web platform. |
| `AADSTS50105` | The signed-in user isn't assigned to a role for the app | Assign the user, or a group they are in, to an app role (step 4). |
| `AADSTS700016` | The application wasn't found in the directory/tenant | Check the client ID and the tenant ID. |
| `AADSTS90002` | The tenant name wasn't found | Check the tenant ID. A national-cloud tenant needs the generic form. |
| `AADSTS50194` | The application isn't configured as multitenant and a `/common` endpoint was used | Not reachable from the Entra form. It means a hand-built generic provider points at `/common`. |
| `AADSTS7000215` | Invalid client secret provided | The secret's Value was mistyped, or its Secret ID was pasted instead. |
| `AADSTS7000222` | The provided client secret keys are expired | Create a new secret and save it with its expiry date. |
| `AADSTS700027` | Client assertion failed signature validation | The active certificate is not the one uploaded to Entra, or it has expired. Upload the active certificate, or generate, upload and activate a new one. |
| `AADSTS7000218` | The request body must contain `client_assertion` or `client_secret` | The provider has no usable credential, for example after a restore onto a server with a different key. Enter the secret again or generate a new certificate. |
| `AADSTS7000112` | The application is disabled | Re-enable the enterprise application in Entra. |

The token-endpoint codes (`AADSTS7000215`, `AADSTS7000222`, `AADSTS700027`, `AADSTS7000218`) never reach Mino's logs, because Mino does not record the provider's error text. Mino shows `client_auth_failed`; find the code in Entra's sign-in log.
