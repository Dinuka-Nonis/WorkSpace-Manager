"""
diagnose_pyvda.py — Run this to see the real AppView API on your pyvda install.
Usage: python diagnose_pyvda.py
"""
import pyvda, inspect

print(f"pyvda version: {pyvda.__version__ if hasattr(pyvda, '__version__') else 'unknown'}")
print()

# What does AppView actually have?
app_views = pyvda.get_apps_by_z_order()
print(f"get_apps_by_z_order() returned {len(app_views)} items")

if app_views:
    app = app_views[0]
    print(f"\nFirst AppView type: {type(app)}")
    print(f"AppView hwnd: {app.hwnd}")
    
    import win32gui
    title = win32gui.GetWindowText(app.hwnd)
    print(f"AppView window title: {title!r}")
    
    print("\nAll AppView attributes and methods:")
    for name in dir(app):
        if not name.startswith('__'):
            val = getattr(app, name, '???')
            kind = 'method' if callable(val) else 'property'
            print(f"  .{name} [{kind}]", end="")
            if not callable(val):
                print(f" = {val!r}", end="")
            print()
    
    print("\nTrying common desktop-id accessors:")
    for attr in ['desktop_id', 'virtual_desktop', 'desktop', 'desktop_guid',
                 'view_id', 'get_desktop', 'is_on_desktop']:
        try:
            val = getattr(app, attr)
            if callable(val):
                result = val()
                print(f"  app.{attr}() = {result!r}  ✓")
            else:
                print(f"  app.{attr} = {val!r}  ✓")
        except Exception as e:
            print(f"  app.{attr} → ERROR: {e}")

print()
print("VirtualDesktop methods:")
vd = pyvda.VirtualDesktop.current()
for name in dir(vd):
    if not name.startswith('__'):
        val = getattr(vd, name, '???')
        kind = 'method' if callable(val) else 'property'
        print(f"  .{name} [{kind}]", end="")
        if not callable(val):
            print(f" = {val!r}", end="")
        print()
