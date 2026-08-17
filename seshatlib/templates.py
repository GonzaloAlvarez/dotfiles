import jinja2
from jinja2 import StrictUndefined, nodes


class TemplateError(Exception):
    pass


_env = jinja2.Environment(
    undefined=StrictUndefined,
    loader=None,
    keep_trailing_newline=True,
    autoescape=False,
)

_FORBIDDEN_NODES = (nodes.Include, nodes.Extends, nodes.Import, nodes.FromImport)


def render(data, context, where=""):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise TemplateError(f"{where}: template is not valid UTF-8: {e}")
    try:
        ast = _env.parse(text)
    except jinja2.TemplateSyntaxError as e:
        raise TemplateError(f"{where}: template syntax error: {e}")
    for node in ast.find_all(_FORBIDDEN_NODES):
        raise TemplateError(f"{where}: template includes, imports, and inheritance are not allowed")
    try:
        return _env.from_string(text).render(**context).encode("utf-8")
    except jinja2.UndefinedError as e:
        raise TemplateError(f"{where}: undefined template variable: {e}")
    except jinja2.TemplateError as e:
        raise TemplateError(f"{where}: template rendering failed: {e}")


def build_context(variables, facts, bundle, home, source_commit):
    return {
        "vars": dict(variables or {}),
        "system": {"os": facts.os, "arch": facts.arch, "hostname": facts.hostname},
        "user": {"name": facts.user, "home": str(home)},
        "bundle": {"name": bundle.name, "source_commit": source_commit},
    }
