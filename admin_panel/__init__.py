"""Admin panel package initializer."""

from flask import Flask


def register_admin_panel(app: Flask) -> None:
    """Register all admin panel blueprints on the given Flask app."""
    from .roles import bp as roles_bp
    from .employees import bp as employees_bp
    from .areas import bp as areas_bp
    from .schedules import bp as schedules_bp
    from .calendars import bp as calendars_bp

    app.register_blueprint(roles_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(areas_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(calendars_bp)


__all__ = ["register_admin_panel"]
