import threading

import requests


def build_line_headers(config):
    # LINE Management API 需要 Bearer token。
    return {
        'Authorization': f'Bearer {config.line_access_token}',
        'Content-Type': 'application/json'
    }


def get_ngrok_api_candidates(config):
    # 優先用使用者指定的 ngrok API，找不到再試常見預設位置。
    candidates = []
    if config.ngrok_api_url:
        candidates.append(config.ngrok_api_url)
    candidates.extend([
        'http://127.0.0.1:4040/api/tunnels',
        'http://localhost:4040/api/tunnels',
        'http://ngrok-tunnel:4040/api/tunnels'
    ])
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def discover_ngrok_public_url(config, state, logger):
    app_port = str(config.flask_port)
    last_error = None
    for api_url in get_ngrok_api_candidates(config):
        try:
            response = requests.get(api_url, timeout=5)
            response.raise_for_status()
            payload = response.json()
            tunnels = payload.get('tunnels', [])
            if not tunnels:
                continue

            ranked = []
            for tunnel in tunnels:
                public_url = (tunnel or {}).get('public_url', '').strip()
                config_info = (tunnel or {}).get('config', {})
                addr = str(config_info.get('addr', ''))
                proto = str((tunnel or {}).get('proto', ''))
                if not public_url.startswith('https://'):
                    continue
                # 挑選最像是目前 Flask 服務對外入口的 tunnel。
                score = 0
                if proto == 'https':
                    score += 4
                if app_port and app_port in addr:
                    score += 2
                if 'xlx-workstation' in addr or 'localhost' in addr or '127.0.0.1' in addr:
                    score += 1
                ranked.append((score, public_url))

            if ranked:
                ranked.sort(reverse=True)
                selected_url = ranked[0][1].rstrip('/')
                if state.last_detected_ngrok_url != selected_url:
                    logger.info('Detected ngrok public URL from %s: %s', api_url, selected_url)
                    state.last_detected_ngrok_url = selected_url
                else:
                    logger.debug('ngrok public URL unchanged: %s', selected_url)
                return selected_url
        except Exception as e:
            last_error = e

    if last_error:
        logger.warning('Unable to discover ngrok public URL: %s', last_error)
    return None


def get_desired_webhook_url(config, state, logger):
    # webhook URL 來源優先順序：固定 public_base_url，其次才是動態偵測 ngrok。
    base_url = config.public_base_url or discover_ngrok_public_url(config, state, logger)
    if not base_url:
        return None
    webhook_path = config.line_webhook_path if config.line_webhook_path.startswith('/') else f'/{config.line_webhook_path}'
    return f'{base_url}{webhook_path}'


def get_line_webhook_info(config):
    response = requests.get(
        f'{config.line_api_base_url}/endpoint',
        headers=build_line_headers(config),
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def set_line_webhook_endpoint(config, endpoint_url):
    response = requests.put(
        f'{config.line_api_base_url}/endpoint',
        headers=build_line_headers(config),
        json={'endpoint': endpoint_url},
        timeout=10
    )
    response.raise_for_status()
    return response.json() if response.content else {}


def test_line_webhook_endpoint(config, endpoint_url=None):
    payload = {'endpoint': endpoint_url} if endpoint_url else {}
    response = requests.post(
        f'{config.line_api_base_url}/test',
        headers=build_line_headers(config),
        json=payload,
        timeout=15
    )
    response.raise_for_status()
    return response.json()


def sync_line_webhook(config, state, logger, force=False):
    desired_url = get_desired_webhook_url(config, state, logger)
    if not desired_url:
        logger.info('Webhook sync skipped because no public URL is available yet')
        return False
    if not force and state.last_synced_webhook_url == desired_url:
        return False

    try:
        current_info = get_line_webhook_info(config)
        current_url = (current_info or {}).get('endpoint', '').rstrip('/')
        if not force and current_url == desired_url:
            state.last_synced_webhook_url = desired_url
            return False

        # 只有目標 URL 真的變了才更新，避免無意義重複呼叫 LINE API。
        logger.info('Updating LINE webhook URL to %s', desired_url)
        set_line_webhook_endpoint(config, desired_url)
        state.last_synced_webhook_url = desired_url

        if config.line_webhook_test_enabled:
            test_result = test_line_webhook_endpoint(config)
            logger.info('LINE webhook test result: success=%s status=%s', test_result.get('success'), test_result.get('statusCode'))
        return True
    except Exception as e:
        logger.warning('Failed to sync LINE webhook URL: %s', e)
        return False


def webhook_sync_worker(config, state, logger):
    if config.webhook_sync_startup_delay_seconds > 0:
        logger.info('Webhook sync worker will start in %s seconds', config.webhook_sync_startup_delay_seconds)
        threading.Event().wait(config.webhook_sync_startup_delay_seconds)

    # 常駐背景輪詢 ngrok / public URL 變化，必要時自動同步到 LINE。
    while True:
        try:
            sync_line_webhook(config, state, logger)
        except Exception:
            logger.exception('Unexpected error in webhook sync worker')
        threading.Event().wait(max(config.webhook_sync_interval_seconds, 5))
