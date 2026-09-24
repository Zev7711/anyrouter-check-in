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
