import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import checkin
from utils.config import AccountConfig, AppConfig


async def test_falls_back_to_session_cookies_when_email_login_fails():
	account = AccountConfig(cookies={'session': 's'}, api_user='1', email='a@b.c', password='p')
	with (
		patch.object(checkin, 'login_with_credentials', AsyncMock(return_value=None)),
		patch.object(checkin, 'prepare_cookies', AsyncMock(return_value={'session': 's'})) as prepare,
		patch.object(checkin, 'run_check_in_requests', return_value=(True, None, None)) as run,
	):
		success, _, _ = await checkin.check_in_account(account, 0, AppConfig.load_from_env())

	assert success
	prepare.assert_awaited_once()
	assert run.call_args.args[0] == {'session': 's'}


async def test_fails_when_email_login_fails_without_session():
	account = AccountConfig(cookies=None, api_user='1', email='a@b.c', password='p')
	with patch.object(checkin, 'login_with_credentials', AsyncMock(return_value=None)):
		success, _, _ = await checkin.check_in_account(account, 0, AppConfig.load_from_env())

	assert not success


def test_skips_sign_in_when_session_expired():
	account = AccountConfig(cookies={'session': 's'}, api_user='1')
	provider = AppConfig.load_from_env().get_provider('anyrouter')
	expired = {'success': False, 'status_code': 401, 'error': 'Failed to get user info: HTTP 401'}
	with (
		patch.object(checkin, 'get_user_info', return_value=expired),
		patch.object(checkin, 'execute_check_in') as execute,
	):
		success, _, _ = checkin.run_check_in_requests({'session': 's'}, account, 'acc', provider)

	assert not success
	execute.assert_not_called()


def test_step_summary_written(tmp_path, monkeypatch):
	summary = tmp_path / 'summary.md'
	monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
	accounts = [AccountConfig(cookies={'session': 's'}, api_user='1', name='主账号')]
	details = {
		'account_1': {
			'success': True,
			'after_quota': 125.0,
			'check_in_reward': 25.0,
			'after_used': 3.0,
		}
	}
	checkin.write_step_summary(accounts, details, 1, 1)

	text = summary.read_text(encoding='utf-8')
	assert '1/1' in text and '+$25.00' in text and '主账号' in text


async def test_session_preferred_over_access_token():
	account = AccountConfig(cookies={'session': 's'}, api_user='1', access_token='tok')
	with (
		patch.object(checkin, 'prepare_cookies', AsyncMock(return_value={'acw_tc': 'w', 'session': 's'})),
		patch.object(checkin, 'run_check_in_requests', return_value=(True, None, None)) as run,
	):
		success, _, _ = await checkin.check_in_account(account, 0, AppConfig.load_from_env())

	assert success
	assert run.call_count == 1
	assert run.call_args.args[0]['session'] == 's'
	assert not run.call_args.kwargs.get('extra_headers')


async def test_access_token_only_account():
	account = AccountConfig(cookies=None, api_user='1', access_token='tok')
	with (
		patch.object(checkin, 'prepare_cookies', AsyncMock(return_value={'acw_tc': 'w'})),
		patch.object(checkin, 'run_check_in_requests', return_value=(False, None, None)) as run,
	):
		success, _, _ = await checkin.check_in_account(account, 0, AppConfig.load_from_env())

	assert not success
	assert run.call_args.kwargs['extra_headers'] == {'Authorization': 'Bearer tok'}


def test_access_token_config_aliases():
	from utils.config import AccountConfig as AC

	assert AC.from_dict({'api_user': '1', 'system_access_token': 'a'}, 0).access_token == 'a'
	assert AC.from_dict({'api_user': '1', 'access_token': 'b'}, 0).access_token == 'b'


def test_session_expiry_parsed_and_warned():
	import base64
	from datetime import datetime, timedelta, timezone

	issued = datetime.now(timezone.utc) - timedelta(days=27)
	raw = f'{int(issued.timestamp())}|payload|sig'.encode()
	session = base64.urlsafe_b64encode(raw).decode().rstrip('=')

	expiry = checkin.get_session_expiry({'session': session})
	assert expiry is not None
	assert abs((expiry - (issued + timedelta(days=30))).total_seconds()) < 2

	warnings = checkin.check_session_expiry_warnings([AccountConfig(cookies={'session': session}, api_user='1')])
	assert len(warnings) == 1 and '过期' in warnings[0]

	fresh = base64.urlsafe_b64encode(f'{int(datetime.now(timezone.utc).timestamp())}|p'.encode()).decode()
	assert checkin.check_session_expiry_warnings([AccountConfig(cookies={'session': fresh}, api_user='1')]) == []
	assert checkin.get_session_expiry({'session': 'not-base64!!'}) is None
