#!/usr/bin/env python3
"""Generate/check the deterministic contract inventory for every API route."""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.http_cache import api_success_cache_class  # noqa: E402

OUTPUT_PATH = ROOT / 'docs' / 'api-route-contracts.json'
SCHEMA_VERSION = 1
_AUTH_FAILURES = {
    'editor': ({401, 503}, {'error', 'login_required'}),
    'admin': ({401, 403, 503}, {'error', 'login_required'}),
}
_TYPED_ERROR_STATUSES = {
    'ValidationError': 400,
    'NotFoundError': 404,
    'ConflictError': 409,
    'UpstreamError': 502,
    'DependencyUnavailableError': 503,
    'PersistenceError': 500,
}


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _jsonify_shape(call: ast.Call) -> tuple[set[str], bool]:
    keys = {kw.arg for kw in call.keywords if kw.arg}
    dynamic = any(kw.arg is None for kw in call.keywords)
    if not call.args:
        return keys, dynamic
    first = call.args[0]
    if isinstance(first, ast.Dict):
        for key in first.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
            else:
                dynamic = True
    else:
        dynamic = True
    if len(call.args) > 1:
        dynamic = True
    return keys, dynamic


class _FunctionContractVisitor(ast.NodeVisitor):
    """Collect only the selected function body, excluding nested functions."""

    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.statuses = {200}
        self.dynamic_status = False
        self.success_keys: set[str] = set()
        self.error_keys: set[str] = set()
        self.dynamic_success = False
        self.dynamic_error = False
        self.kinds: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_Return(self, node: ast.Return) -> None:
        value = node.value
        status = 200
        response_node = value
        if isinstance(value, ast.Tuple) and value.elts:
            response_node = value.elts[0]
            if len(value.elts) > 1:
                status_node = value.elts[1]
                if isinstance(status_node, ast.Constant) and isinstance(status_node.value, int):
                    status = status_node.value
                else:
                    self.dynamic_status = True
        self.statuses.add(status)

        calls = [
            child for child in ast.walk(response_node)
            if isinstance(child, ast.Call)
        ] if response_node is not None else []
        jsonify_calls = [call for call in calls if _call_name(call) == 'jsonify']
        target_keys = self.error_keys if status >= 400 else self.success_keys
        if jsonify_calls:
            self.kinds.add('json')
            for call in jsonify_calls:
                keys, dynamic = _jsonify_shape(call)
                target_keys.update(keys)
                if status >= 400:
                    self.dynamic_error = self.dynamic_error or dynamic
                else:
                    self.dynamic_success = self.dynamic_success or dynamic
        else:
            names = {_call_name(call) for call in calls}
            if 'send_file' in names or 'send_from_directory' in names:
                self.kinds.add('binary')
            elif 'redirect' in names:
                self.kinds.add('redirect')
            elif 'Response' in names:
                self.kinds.add('response')
            elif response_node is not None:
                self.kinds.add('delegated-or-dynamic')
                if status >= 400:
                    self.dynamic_error = True
                else:
                    self.dynamic_success = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _call_name(node) == 'abort' and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                self.statuses.add(arg.value)
                if arg.value >= 400:
                    self.error_keys.add('error')
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        error_name = _call_name(node.exc) if node.exc else None
        if error_name in _TYPED_ERROR_STATUSES:
            self.statuses.add(_TYPED_ERROR_STATUSES[error_name])
            self.error_keys.update({'error', 'code'})
        self.generic_visit(node)


@lru_cache(maxsize=None)
def _module_tree(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text(encoding='utf-8'), filename=path)


def _function_node(view: Callable) -> tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]:
    original = inspect.unwrap(view)
    source_path = Path(inspect.getsourcefile(original) or '').resolve()
    if not source_path.is_file():
        raise RuntimeError(f'cannot resolve route source for {view!r}')
    tree = _module_tree(str(source_path))
    candidates = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == original.__name__
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f'expected one function {original.__name__} in {source_path}, '
            f'found {len(candidates)}'
        )
    return source_path, candidates[0]


def _response_contract(view: Callable, auth: str) -> dict[str, Any]:
    source_path, function = _function_node(view)
    visitor = _FunctionContractVisitor(function)
    visitor.visit(function)
    auth_failures = _AUTH_FAILURES.get(auth)
    if auth_failures:
        statuses, keys = auth_failures
        visitor.statuses.update(statuses)
        visitor.error_keys.update(keys)
    return {
        'declared_statuses': sorted(visitor.statuses),
        'dynamic_status': visitor.dynamic_status,
        'success_keys': sorted(visitor.success_keys),
        'error_keys': sorted(visitor.error_keys),
        'dynamic_success': visitor.dynamic_success,
        'dynamic_error': visitor.dynamic_error,
        'response_kinds': sorted(visitor.kinds) or ['implicit'],
        'source': str(source_path.relative_to(ROOT)),
    }


def build_inventory() -> dict[str, Any]:
    from app import create_app

    flask_app = create_app({'core', 'reading', 'memorize', 'breathing', 'editor'})
    routes = []
    for rule in flask_app.url_map.iter_rules():
        if not rule.rule.startswith('/api/'):
            continue
        view = flask_app.view_functions[rule.endpoint]
        blueprint = rule.endpoint.split('.', 1)[0] if '.' in rule.endpoint else None
        auth = getattr(view, '_athar_auth_policy', 'public')
        response = _response_contract(view, auth)
        routes.append({
            'path': rule.rule,
            'endpoint': rule.endpoint,
            'methods': sorted(set(rule.methods or ()) - {'OPTIONS'}),
            'feature': blueprint or 'application',
            'availability': (
                'editor-feature' if blueprint == 'editor' else 'default-feature'
            ),
            'auth': auth,
            'success_cache': api_success_cache_class(rule.rule, blueprint),
            **response,
        })
    routes.sort(key=lambda row: (row['path'], row['endpoint']))
    return {
        'schema_version': SCHEMA_VERSION,
        'generated_by': 'pipeline/generate_route_contracts.py',
        'route_count': len(routes),
        'routes': routes,
    }


def _serialized(inventory: dict[str, Any]) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check', action='store_true',
        help='fail if the committed inventory differs from current routes',
    )
    parser.add_argument('--output', type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    rendered = _serialized(build_inventory())
    output = args.output.resolve()
    if args.check:
        existing = output.read_text(encoding='utf-8') if output.is_file() else ''
        if existing != rendered:
            print(
                f'route contract drift: regenerate with {Path(__file__).name}',
                file=sys.stderr,
            )
            return 1
        print(f'route contract OK: {output}')
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding='utf-8')
    print(f'wrote {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
