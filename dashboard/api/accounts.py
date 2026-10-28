"""Session login and admin-managed users; no public registration."""
import os
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from core.research import accounts, identity, store

router = APIRouter(prefix='/api')
PUBLIC = {'/', '/api/auth/session', '/api/auth/login', '/api/auth/setup'}
REFRESH_PATHS = {
    '/api/settings', '/api/jobs/universe', '/api/jobs/ingest', '/api/jobs/universe-expansion',
    '/api/jobs/backtest-history', '/api/jobs/sectors', '/api/company/fundamentals-pull',
    '/api/company/evidence', '/api/company/research', '/api/company/reviews',
    '/api/investor/refresh', '/api/investor/interpret', '/api/investor/cycle',
    '/api/investor/scores/refresh', '/api/investor/reviews/complete',
    '/api/investor/database/sync', '/api/investor/monitor-settings',
}


def admin_request(path, method):
    path = path.rstrip('/')
    return path.startswith('/api/admin') or method not in ('GET', 'HEAD', 'OPTIONS') and path in REFRESH_PATHS


def require_admin():
    if not identity.admin():
        raise HTTPException(403, 'Only manoj can manage users, service credentials and shared data refreshes.')


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


def cookie(response, token):
    response.set_cookie(accounts.COOKIE, token, max_age=accounts.SESSION_SECONDS,
                        httponly=True, secure=bool(os.environ.get('TRADER_PUBLIC_ORIGIN')),
                        samesite='strict', path='/')


@router.get('/auth/session')
def status(request: Request):
    return dict(enabled=accounts.enabled(), user=getattr(request.state, 'user', None),
                setup_required=accounts.enabled() and not store.read('auth/users/manoj')
                and not bool(os.environ.get('TRADER_PUBLIC_ORIGIN')))


@router.post('/auth/setup')
def setup(value: Login):
    if not accounts.enabled() or os.environ.get('TRADER_PUBLIC_ORIGIN'):
        raise HTTPException(403, 'Public admin setup is disabled. Configure the initial admin password on the server.')
    if value.username != 'manoj':
        raise ValueError('The administrator username is manoj.')
    user = accounts.create('manoj', value.password.get_secret_value(), bootstrap=True)
    accounts.migrate_legacy()
    return user


@router.post('/auth/login')
def login(value: Login, request: Request, response: Response):
    if not accounts.enabled():
        raise HTTPException(404)
    token, user = accounts.login(value.username, value.password.get_secret_value(), request.client.host)
    if not token:
        raise HTTPException(429 if user == 'limited' else 401,
                            'Too many login attempts. Try again in 15 minutes.' if user == 'limited' else 'Invalid username or password.')
    cookie(response, token)
    return dict(user=user)


@router.post('/auth/logout')
def logout(request: Request, response: Response):
    accounts.logout(request.cookies.get(accounts.COOKIE))
    response.delete_cookie(accounts.COOKIE, path='/', samesite='strict',
                           secure=bool(os.environ.get('TRADER_PUBLIC_ORIGIN')), httponly=True)
    return dict(logged_out=True)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=6, max_length=128)


@router.put('/auth/password')
def change_password(value: PasswordChange, response: Response):
    if not identity.username():
        raise HTTPException(401, 'Sign in to change your password.')
    user = store.read('auth/users/'+identity.username())
    if not accounts.matches(value.current_password.get_secret_value(), user['password_hash']):
        raise HTTPException(400, 'Current password is incorrect.')
    accounts.update(identity.username(), password=value.password.get_secret_value())
    response.delete_cookie(accounts.COOKIE, path='/')
    return dict(logged_out=True)


@router.get('/admin/users')
def users():
    require_admin()
    return dict(users=accounts.users())


@router.post('/admin/users')
def create_user(value: Login):
    require_admin()
    return accounts.create(value.username, value.password.get_secret_value())


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: SecretStr | None = Field(None, min_length=6, max_length=128)
    enabled: bool | None = None


@router.put('/admin/users/{username}')
def update_user(username: str, value: UserUpdate):
    require_admin()
    username = accounts.normalize(username)
    if username == 'manoj' and value.password is not None:
        raise ValueError('Use Account → Change password to change your own password.')
    return accounts.update(username, password=value.password.get_secret_value() if value.password else None,
                           active=value.enabled)


class Services(BaseModel):
    model_config = ConfigDict(extra='forbid')
    market_token: SecretStr | None = Field(None, min_length=20, max_length=10000)
    research_key: SecretStr | None = Field(None, min_length=20, max_length=1000)
    research_model: str | None = Field(None, min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9._:-]+$')


@router.get('/admin/services')
def services():
    require_admin()
    from core.research import service_credentials
    return service_credentials.status()


@router.put('/admin/services')
def save_services(value: Services):
    require_admin()
    from core.research import service_credentials
    if value.market_token:
        token = value.market_token.get_secret_value().strip()
        if len(token) < 20:
            raise ValueError('Enter a valid market-data token.')
        store.save_token(token)
    service_credentials.save(value.research_key.get_secret_value().strip() if value.research_key else None,
                             value.research_model)
    return service_credentials.status()
