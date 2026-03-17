from modeltranslation.translator import translator, TranslationOptions

from webapp.models import FAQCategory, FAQ


class FAQCategoryTranslationOptions(TranslationOptions):
    fields = ('name',)


class FAQTranslationOptions(TranslationOptions):
    fields = ('question', 'answer')


translator.register(FAQCategory, FAQCategoryTranslationOptions)
translator.register(FAQ, FAQTranslationOptions)
