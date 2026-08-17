import json

import pytest

from seshatlib import templates
from seshatlib.manifest import Bundle, Facts
from seshatlib.templates import TemplateError


@pytest.fixture
def context(fake_home):
    facts = Facts(os="darwin", arch="arm64", user="galvarez", hostname="box")
    bundle = Bundle(name="llm.claude.bedrock")
    return templates.build_context(
        {"aws_profile": "bedrock", "aws_region": "us-east-2"}, facts, bundle, fake_home, "abc123"
    )


def test_render_variables(context):
    out = templates.render(b"profile={{ vars.aws_profile }}", context)
    assert out == b"profile=bedrock"


def test_render_system_and_user(context, fake_home):
    out = templates.render(b"{{ system.os }}/{{ user.name }}/{{ bundle.name }}", context)
    assert out == b"darwin/galvarez/llm.claude.bedrock"
    out = templates.render(b"{{ user.home }}", context)
    assert out == str(fake_home).encode()


def test_undefined_variable_fails(context):
    with pytest.raises(TemplateError, match="undefined"):
        templates.render(b"{{ vars.nope }}", context)


def test_unknown_context_name_fails(context):
    with pytest.raises(TemplateError, match="undefined"):
        templates.render(b"{{ environ }}", context)
    with pytest.raises(TemplateError, match="undefined"):
        templates.render(b"{{ os }}", context)


def test_include_rejected(context):
    with pytest.raises(TemplateError, match="not allowed"):
        templates.render(b"{% include '/etc/passwd' %}", context)


def test_extends_rejected(context):
    with pytest.raises(TemplateError, match="not allowed"):
        templates.render(b"{% extends 'base' %}", context)


def test_import_rejected(context):
    with pytest.raises(TemplateError, match="not allowed"):
        templates.render(b"{% import 'macros' as m %}", context)
    with pytest.raises(TemplateError, match="not allowed"):
        templates.render(b"{% from 'macros' import x %}", context)


def test_syntax_error_reported(context):
    with pytest.raises(TemplateError, match="syntax"):
        templates.render(b"{% if %}", context)


def test_tojson_escaping(fake_home):
    facts = Facts(os="darwin", arch="arm64", user="galvarez", hostname="box")
    bundle = Bundle(name="b")
    ctx = templates.build_context({"v": 'tricky "quote" \\ value'}, facts, bundle, fake_home, "c")
    out = templates.render(b'{"x": {{ vars.v | tojson }}}', ctx)
    assert json.loads(out) == {"x": 'tricky "quote" \\ value'}


def test_required_filters_available(context):
    out = templates.render(
        b"{{ vars.aws_profile | upper }} {{ ' pad ' | trim }} {{ vars.missing | default('d') }}",
        context,
    )
    assert out == b"BEDROCK pad d"


def test_deterministic_render(context):
    src = b"{{ vars.aws_profile }}-{{ system.arch }}"
    assert templates.render(src, context) == templates.render(src, context)


def test_context_is_exactly_the_allowed_surface(context):
    assert set(context) == {"vars", "system", "user", "bundle"}
    assert set(context["system"]) == {"os", "arch", "hostname"}
    assert set(context["user"]) == {"name", "home"}
    assert set(context["bundle"]) == {"name", "source_commit"}
