from django.contrib.admin import AdminSite


class CustomAdminSite(AdminSite):
    """Custom admin site that reorganizes models into logical groups."""

    ADMIN_GROUPS = [
        ('auth_group', 'Authentication and Authorization', [
            ('auth', 'User'),
            ('auth', 'Group'),
        ]),
        ('social_auth_group', 'Python Social Auth', [
            ('social_django', 'Association'),
            ('social_django', 'Code'),
            ('social_django', 'Nonce'),
            ('social_django', 'Partial'),
            ('social_django', 'UserSocialAuth'),
        ]),
        ('location_group', 'Location', [
            ('webapp', 'Location'),
            ('webapp', 'LocationFollower'),
            ('webapp', 'LocationGame'),
            ('webapp', 'Member'),
            ('webapp', 'Membership'),
            ('webapp', 'TelegramGroupConfig'),
            ('webapp', 'TelegramSetupToken'),
        ]),
        ('tables_group', 'Tables', [
            ('webapp', 'Table'),
            ('webapp', 'Player'),
            ('webapp', 'Comment'),
        ]),
        ('users_group', 'Users', [
            ('webapp', 'UserProfile'),
            ('webapp', 'GuestProfile'),
            ('webapp', 'Notification'),
        ]),
        ('games_group', 'Games', [
            ('webapp', 'Game'),
        ]),
        ('events_group', 'Events', [
            ('webapp', 'Event'),
        ]),
        ('static_pages_group', 'Static pages', [
            ('webapp', 'FAQ'),
            ('webapp', 'FAQCategory'),
        ]),
    ]

    def get_app_list(self, request, app_label=None):
        if app_label:
            return super().get_app_list(request, app_label)

        app_dict = self._build_app_dict(request)

        model_index = {}
        for app_data in app_dict.values():
            for model_data in app_data['models']:
                key = (app_data['app_label'], model_data['object_name'])
                model_index[key] = model_data

        result = []
        for group_label, group_name, model_keys in self.ADMIN_GROUPS:
            models_in_group = [model_index[k] for k in model_keys if k in model_index]
            if not models_in_group:
                continue
            result.append({
                'name': group_name,
                'app_label': group_label,
                'app_url': '/admin/',
                'has_module_perms': True,
                'models': models_in_group,
            })

        return result
