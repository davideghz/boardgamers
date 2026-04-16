import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from webapp.models import PushSubscription

logger = logging.getLogger(__name__)


def manifest_json(request):
    return render(request, 'pwa/manifest.json', content_type='application/manifest+json')


def service_worker_js(request):
    return render(request, 'pwa/service-worker.js', content_type='application/javascript')


@login_required
@require_http_methods(['POST', 'DELETE'])
def push_subscribe(request):
    user_profile = request.user.user_profile

    if request.method == 'DELETE':
        body = json.loads(request.body)
        endpoint = body.get('endpoint', '')
        PushSubscription.objects.filter(user_profile=user_profile, endpoint=endpoint).delete()
        return JsonResponse({'status': 'unsubscribed'})

    body = json.loads(request.body)
    endpoint = body.get('endpoint', '')
    keys = body.get('keys', {})
    p256dh = keys.get('p256dh', '')
    auth = keys.get('auth', '')

    if not endpoint or not p256dh or not auth:
        return JsonResponse({'error': 'invalid subscription'}, status=400)

    PushSubscription.objects.update_or_create(
        user_profile=user_profile,
        endpoint=endpoint,
        defaults={'p256dh': p256dh, 'auth': auth},
    )
    return JsonResponse({'status': 'subscribed'})
