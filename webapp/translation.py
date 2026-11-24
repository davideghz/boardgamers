from modeltranslation.translator import translator, TranslationOptions

from webapp.models import Banner, FAQCategory, FAQ


class FAQCategoryTranslationOptions(TranslationOptions):
    fields = ('name',)


class FAQTranslationOptions(TranslationOptions):
    fields = ('question', 'answer')


translator.register(FAQCategory, FAQCategoryTranslationOptions)
translator.register(FAQ, FAQTranslationOptions)


class BannerTranslationOptions(TranslationOptions):
    fields = ('title', 'message', 'cover_alt', 'action_label')
    required_languages = {'default': ('message',)}


translator.register(Banner, BannerTranslationOptions)
