# API route contracts

[`api-route-contracts.json`](api-route-contracts.json) is the generated,
reviewable contract for every Flask route under `/api/`. It records:

- URL rule and HTTP methods;
- feature/deployment availability;
- public, editor, or admin authentication;
- successful-response cache class;
- explicitly declared HTTP statuses;
- statically visible top-level success/error JSON keys;
- whether a response shape or status is dynamic/delegated;
- response kind and owning source module.

CI compares the committed file with the live Flask route map and source AST.
An added/removed route, method, auth decorator, cache class, declared status, or
visible JSON key fails `tests/test_route_contracts.py`.

For an intentional API change:

```bash
python3 pipeline/generate_route_contracts.py
git diff -- docs/api-route-contracts.json
python3 pipeline/generate_route_contracts.py --check
python3 -m pytest -q tests/test_route_contracts.py
```

Review the JSON diff before committing it. Do not regenerate merely to silence
a failure: confirm that authentication, caching, statuses, and keys changed on
purpose. `dynamic_success`/`dynamic_error` identifies endpoints whose payload
comes from a helper, variable, list, binary response, or delegated route; the
inventory still guards their method/auth/cache/status contract, while focused
endpoint tests remain responsible for their runtime payload shape.
