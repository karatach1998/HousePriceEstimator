import os
import streamlit.components.v1 as components


_RELEASE = True

if not _RELEASE:
    _component_func = components.declare_component(
        "ymap_component",
        url="http://172.23.213.15:3001"
    )
else:
    component_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(component_dir, 'frontend', 'build')
    _component_func = components.declare_component("ymap_components", path=build_dir)


def ymap_component(label=None, pos=None, initial=None, key=None):
    return _component_func(label=label, pos=pos, initial=initial, key=key)
