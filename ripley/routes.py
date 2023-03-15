"""
Copyright ©2023. The Regents of the University of California (Regents). All Rights Reserved.

Permission to use, copy, modify, and distribute this software and its documentation
for educational, research, and not-for-profit purposes, without fee and without a
signed licensing agreement, is hereby granted, provided that the above copyright
notice, this paragraph and the following two paragraphs appear in all copies,
modifications, and distributions.

Contact The Office of Technology Licensing, UC Berkeley, 2150 Shattuck Avenue,
Suite 510, Berkeley, CA 94720-1620, (510) 643-7201, otl@berkeley.edu,
http://ipira.berkeley.edu/industry-info for commercial licensing opportunities.

IN NO EVENT SHALL REGENTS BE LIABLE TO ANY PARTY FOR DIRECT, INDIRECT, SPECIAL,
INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS, ARISING OUT OF
THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF REGENTS HAS BEEN ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.

REGENTS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE. THE
SOFTWARE AND ACCOMPANYING DOCUMENTATION, IF ANY, PROVIDED HEREUNDER IS PROVIDED
"AS IS". REGENTS HAS NO OBLIGATION TO PROVIDE MAINTENANCE, SUPPORT, UPDATES,
ENHANCEMENTS, OR MODIFICATIONS.
"""
import datetime
import json
import traceback

from flask import jsonify, make_response, redirect, request, session
from flask_login import current_user, LoginManager
from werkzeug.exceptions import HTTPException


def register_routes(app):
    """Register app routes."""
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.user_loader(_user_loader)
    login_manager.anonymous_user = _user_loader

    # Register API routes.
    import ripley.api.auth_controller
    import ripley.api.canvas_course_controller
    import ripley.api.canvas_user_controller
    import ripley.api.canvas_utility_controller
    import ripley.api.config_controller
    import ripley.api.job_controller
    import ripley.api.lti_controller
    import ripley.api.mailing_lists_controller
    import ripley.api.status_controller
    import ripley.api.user_controller

    # Register error handlers.
    import ripley.api.error_handlers

    index_html = open(app.config['INDEX_HTML']).read()

    @app.login_manager.unauthorized_handler
    def unauthorized_handler():
        return jsonify(success=False, data={'login_required': True}, message='Unauthorized'), 401

    # Unmatched API routes return a 404.
    @app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT'])
    def handle_unmatched_api_route(**kwargs):
        app.logger.error('The requested resource could not be found.')
        raise ripley.api.errors.ResourceNotFoundError('The requested resource could not be found.')

    # Non-API routes are handled by the front end.
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>', methods=['GET', 'POST', 'PUT'])
    def front_end_route(**kwargs):
        vue_base_url = app.config['VUE_LOCALHOST_BASE_URL']
        return redirect(vue_base_url + request.full_path) if vue_base_url else make_response(index_html)

    @app.errorhandler(Exception)
    def handle_exception(e):
        subject = str(e)
        if isinstance(e, HTTPException):
            app.logger.warn(f"""\n\n{type(e).__name__} {subject}\n{traceback.format_exc()}\n""")
        else:
            message = f'{e}\n\n<pre>{traceback.format_exc()}</pre>'
            app.logger.warn(message)
            # # TODO? Notify Ripley Ops teams
            # send_system_error_email(
            #     message=message,
            #     subject=f'{subject[:50]}...' if len(subject) > 50 else subject,
            # )

        return {'message': subject}, 400

    @app.before_request
    def before_request():
        session.permanent = True
        app.permanent_session_lifetime = datetime.timedelta(minutes=app.config['INACTIVE_SESSION_LIFETIME'])
        session.modified = True

    @app.after_request
    def after_request(response):
        _set_session(response)
        if app.config['RIPLEY_ENV'] == 'development':
            # In development the response can be shared with requesting code from any local origin.
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            response.headers['Access-Control-Allow-Origin'] = app.config['VUE_LOCALHOST_BASE_URL']
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
        else:
            response.headers['Access-Control-Allow-Origin'] = app.config['CANVAS_API_URL']
        if request.full_path.startswith('/api'):
            forwarded_for = request.headers.get('X-Forwarded-For')
            forwarded_for = forwarded_for.split(',')[0] if forwarded_for else None

            log_message = ' '.join([
                forwarded_for or request.remote_addr,
                request.method,
                request.full_path,
                response.status,
            ])
            if response.status_code >= 500:
                app.logger.error(log_message)
            elif response.status_code >= 400:
                app.logger.warning(log_message)
            else:
                app.logger.info(log_message)
        return response


def _set_session(response):
    from flask import current_app as app

    cookie_name = app.config['REMEMBER_COOKIE_NAME']
    if cookie_name in request.cookies:
        cookie_value = request.cookies[cookie_name]
        composite_key = json.loads(cookie_value.split('|')[0])
        app.logger.debug(f'cookie: {composite_key}')
        if composite_key['uid'] == current_user.uid and composite_key['canvas_course_id'] == current_user.canvas_course_id:
            response.set_cookie(cookie_name, cookie_value, samesite='None', secure=True)


def _user_loader(user_id=None):
    from ripley.models.user import User

    composite_key = json.loads(user_id) if user_id else {}
    canvas_course_id = composite_key.get('canvas_course_id', None)
    uid = composite_key.get('uid', None)
    user_id = User.get_serialized_composite_key(canvas_course_id=canvas_course_id, uid=uid)
    return User(user_id)
