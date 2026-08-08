"""Failure contracts: stable public JSON, detailed failures in logs only."""
from __future__ import annotations

import logging

import pytest

from core import supabase_editor as sb
from core.errors import (
    ConflictError,
    DependencyUnavailableError,
    NotFoundError,
    PersistenceError,
    UpstreamError,
    ValidationError,
)
from modules import cv_waqf_ui, editor


@pytest.mark.parametrize(
    ('error_type', 'status', 'code'),
    [
        (ValidationError, 400, 'validation_error'),
        (NotFoundError, 404, 'not_found'),
        (ConflictError, 409, 'conflict'),
        (UpstreamError, 502, 'upstream_error'),
        (DependencyUnavailableError, 503, 'dependency_unavailable'),
        (PersistenceError, 500, 'persistence_error'),
    ],
)
def test_typed_error_defaults(error_type, status, code):
    error = error_type()
    assert error.status_code == status
    assert error.response_payload()['error']
    assert error.response_payload()['code'] == code


def test_typed_error_handler_never_serializes_chained_exception():
    from app import create_app

    test_app = create_app({'core'})

    @test_app.get('/api/_test/typed-error')
    def typed_error_route():
        try:
            raise RuntimeError('/private/db.sqlite: SELECT secret FROM table')
        except RuntimeError as exc:
            raise PersistenceError(
                'تعذّر حفظ البيانات',
                public_fields={'hint': 'حاول مرة أخرى'},
            ) from exc

    response = test_app.test_client().get('/api/_test/typed-error')
    assert response.status_code == 500
    assert response.get_json() == {
        'error': 'تعذّر حفظ البيانات',
        'code': 'persistence_error',
        'hint': 'حاول مرة أخرى',
    }
    assert 'db.sqlite' not in response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'no-store, max-age=0'


def test_editor_spread_hides_builder_failure(client, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError('/private/layout.db: no such table secret_words')

    monkeypatch.setattr(editor, '_build_qatar_page_payload', fail)
    response = client.get('/api/mushaf-editor/spread/1?edition=قطر')
    body = response.get_json()

    assert response.status_code == 500
    assert body['error'] == 'تعذّر تحميل صفحات المحرر'
    assert body['code'] == 'persistence_error'
    assert 'layout.db' not in response.get_data(as_text=True)


def test_cv_page_hides_detector_failure(app, monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)

    def fail(*_args, **_kwargs):
        raise RuntimeError('subprocess stderr: /Users/private/model.onnx')

    monkeypatch.setattr(cv_waqf_ui, '_build_payload', fail)
    response = app.test_client().get('/api/cv-waqf/page/17?edition=البحرين')
    body = response.get_json()

    assert response.status_code == 500
    assert body['error'] == 'تعذّر تحليل صفحة المصحف'
    assert body['code'] == 'persistence_error'
    assert 'train once' in body['hint']
    assert 'model.onnx' not in response.get_data(as_text=True)


def test_supabase_adapter_rejects_non_json_success(monkeypatch, caplog):
    class MalformedResponse:
        status_code = 200
        content = b'<html>proxy failure containing private-token</html>'
        text = content.decode()

        @staticmethod
        def json():
            raise ValueError('not json')

    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-role')
    monkeypatch.setattr(sb.requests, 'request', lambda *_args, **_kwargs: MalformedResponse())

    with caplog.at_level(logging.ERROR), pytest.raises(sb.SupabaseEditorError) as caught:
        sb._request('GET', 'editor_marks')

    assert 'malformed successful response' in str(caught.value)
    assert 'private-token' not in str(caught.value)
    assert 'private-token' in caplog.text


def test_supabase_adapter_rejects_wrong_table_payload_shape(monkeypatch):
    class WrongShapeResponse:
        status_code = 200
        content = b'{"message":"not a PostgREST row set"}'
        text = content.decode()

        @staticmethod
        def json():
            return {'message': 'not a PostgREST row set'}

    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-role')
    monkeypatch.setattr(sb.requests, 'request', lambda *_args, **_kwargs: WrongShapeResponse())

    with pytest.raises(sb.SupabaseEditorError, match='malformed successful response'):
        sb._request('GET', 'editor_marks')


def test_supabase_http_body_is_internal_not_exception_text(monkeypatch, caplog):
    class FailedResponse:
        status_code = 400
        content = b'{"message":"private SQL detail"}'
        text = content.decode()

        @staticmethod
        def json():
            return {'message': 'private SQL detail'}

    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-role')
    monkeypatch.setattr(sb.requests, 'request', lambda *_args, **_kwargs: FailedResponse())

    with caplog.at_level(logging.ERROR), pytest.raises(sb.SupabaseResponseError) as caught:
        sb._request('GET', 'editor_marks')

    assert str(caught.value) == 'Supabase request returned HTTP 400'
    assert 'private SQL detail' not in str(caught.value)
    assert 'private SQL detail' in caught.value.body
    assert 'private SQL detail' in caplog.text
