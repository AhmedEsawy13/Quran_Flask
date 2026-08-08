# Editor authorization policy

This matrix is the contract for routes mounted by the optional `editor`
blueprint. With Supabase disabled, `require_editor` deliberately allows the
local workstation workflow. With Supabase enabled, it requires a valid active
invite session signed by `EDITOR_SESSION_SECRET`.

| Capability | Local mode | Cloud mode | Cache |
|---|---|---|---|
| Editor/review HTML shell | allowed | allowed so login UI can render | `no-store` |
| Public printed-reference/demo data | allowed | allowed where explicitly public | `no-store` |
| Waqf draft/published overlay reads | allowed | editor session | `no-store` |
| Waqf draft writes and review progress | allowed | editor session | `no-store` |
| Layout page/profile/undo/confidence reads | allowed | editor session | `no-store` |
| Layout writes and undo | allowed | editor session | `no-store` |
| Classical-review data and decisions | allowed | editor session | `no-store` |
| CV images, labels, queues, and writes | allowed | editor session | `no-store` |
| Activity/audit API | allowed | editor session | `no-store` |
| Invite administration and publishing | unavailable | admin session | `no-store` |

Cloud authentication fails closed with HTTP 503 when
`EDITOR_SESSION_SECRET` is absent, is the development default, or is shorter
than 32 characters. `SECRET_KEY` is not accepted as a cloud-editor substitute.
Authentication failures remain 401 and authorization failures remain 403.

When adding an editor route:

1. keep the HTML shell public only when it contains the login/recovery UI;
2. decorate draft, reviewer, audit, or working-layout APIs with
   `require_editor`;
3. use `require_admin` only for account administration and publication;
4. add a cloud-mode regression test for the expected 401/403 behavior;
5. never opt an editor-blueprint API into shared/public caching.
