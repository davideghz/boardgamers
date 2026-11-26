"""
Online membership documents: the manager writes them in a visual editor, the
member signs them by drawing their signature, online or in person on a
manager's device. See webapp/services/member_documents.py.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from meta.views import Meta

from webapp.forms import OnlineMembershipDocumentForm, SignMembershipDocumentForm
from webapp.models import Location, Member, MembershipDocument, SignedMembershipDocument
from webapp.services import member_documents


def _managed_location(request, slug):
    location = get_object_or_404(Location, slug=slug)
    if not location.is_manager(request.user.user_profile):
        raise PermissionDenied(_("You don't have permission to manage this location."))
    return location


def _pdf_response(content_or_file, filename):
    if isinstance(content_or_file, bytes):
        response = HttpResponse(content_or_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
    else:
        response = FileResponse(content_or_file, content_type='application/pdf', filename=filename)
    # Personal data: no shared or browser cache.
    response['Cache-Control'] = 'private, no-store'
    return response


class OnlineMembershipDocumentEditView(LoginRequiredMixin, View):
    """Write a new online document, or edit one."""
    template_name = 'locations/location_manage_membership_document_editor.html'

    def _document(self, location, document_uuid):
        if document_uuid is None:
            return None
        return get_object_or_404(
            MembershipDocument, uuid=document_uuid, location=location, kind=MembershipDocument.ONLINE)

    def _render(self, request, location, form, document):
        return render(request, self.template_name, {
            'location': location,
            'form': form,
            'document': document,
            'placeholders': list(member_documents.PLACEHOLDERS.items()),
            'signatures_count': document.signatures.count() if document else 0,
            'meta': Meta(title=_("Membership documents %(name)s - Boardgamers.com") % {'name': location.name}),
        })

    def get(self, request, slug, document_uuid=None):
        location = _managed_location(request, slug)
        document = self._document(location, document_uuid)
        form = OnlineMembershipDocumentForm(instance=document, initial=None if document else {'is_active': True})
        return self._render(request, location, form, document)

    def post(self, request, slug, document_uuid=None):
        location = _managed_location(request, slug)
        document = self._document(location, document_uuid)
        form = OnlineMembershipDocumentForm(request.POST, instance=document)
        if form.is_valid():
            document = form.save(commit=False)
            document.location = location
            document.save()
            messages.success(request, _("Document %(name)s saved.") % {'name': document.name})
            return redirect('location-membership-documents', slug=location.slug)
        return self._render(request, location, form, document)


class MembershipDocumentPreviewView(LoginRequiredMixin, View):
    """The online document as an empty PDF, to check the layout before members sign it."""

    def get(self, request, slug, document_uuid):
        location = _managed_location(request, slug)
        document = get_object_or_404(
            MembershipDocument, uuid=document_uuid, location=location, kind=MembershipDocument.ONLINE)
        return _pdf_response(member_documents.preview_pdf(document), 'preview.pdf')


class BaseSignView(LoginRequiredMixin, View):
    """Shared by the member signing online and the manager collecting a signature in person."""
    template_name = 'locations/location_sign_membership_document.html'
    in_person = False

    def resolve(self, request, slug, document_uuid, member_uuid=None):
        """Return (location, member, document) or raise."""
        raise NotImplementedError

    def unavailable(self, request, location, member):
        """Where to go when the member has no pending or active membership."""
        raise NotImplementedError

    def done_url(self, location, member, membership):
        raise NotImplementedError

    def _render(self, request, location, member, document, form):
        values = member_documents.placeholder_values(member, location)
        return render(request, self.template_name, {
            'location': location,
            'member': member,
            'document': document,
            'form': form,
            'document_html': member_documents.render_html(document.body, values),
            'in_person': self.in_person,
            'cancel_url': self.cancel_url(location, member),
            'meta': Meta(title=_("Sign %(document)s - %(name)s") % {
                'document': document.name, 'name': location.name}),
        })

    def cancel_url(self, location, member):
        raise NotImplementedError

    def _prepare(self, request, slug, document_uuid, member_uuid):
        location, member, document = self.resolve(request, slug, document_uuid, member_uuid)
        membership = member_documents.signing_membership(member) if member else None
        return location, member, document, membership

    def get(self, request, slug, document_uuid, member_uuid=None):
        location, member, document, membership = self._prepare(request, slug, document_uuid, member_uuid)
        if membership is None:
            return self.unavailable(request, location, member)
        if document.signatures.filter(membership=membership).exists():
            messages.info(request, _("This document is already signed."))
            return redirect(self.done_url(location, member, membership))
        form = SignMembershipDocumentForm(instance=member, document=document)
        return self._render(request, location, member, document, form)

    def post(self, request, slug, document_uuid, member_uuid=None):
        location, member, document, membership = self._prepare(request, slug, document_uuid, member_uuid)
        if membership is None:
            return self.unavailable(request, location, member)
        if document.signatures.filter(membership=membership).exists():
            messages.info(request, _("This document is already signed."))
            return redirect(self.done_url(location, member, membership))
        form = SignMembershipDocumentForm(request.POST, instance=member, document=document)
        if not form.is_valid():
            return self._render(request, location, member, document, form)
        # The member's data and the signed copy go together, or not at all.
        with transaction.atomic():
            member = form.save()
            member_documents.sign_document(
                document=document, member=member, membership=membership,
                signature_png=form.cleaned_data['signature'], request=request,
                collected_by=request.user.user_profile if self.in_person else None,
            )
        messages.success(request, _("Document %(name)s signed.") % {'name': document.name})
        return redirect(self.done_url(location, member, membership))


class SignMembershipDocumentView(BaseSignView):
    """A member signs an online document of a location from their own account."""

    def resolve(self, request, slug, document_uuid, member_uuid=None):
        location = get_object_or_404(Location, slug=slug)
        document = get_object_or_404(
            MembershipDocument, uuid=document_uuid, location=location,
            kind=MembershipDocument.ONLINE, is_active=True)
        member = Member.objects.filter(location=location, user_profile=request.user.user_profile).first()
        return location, member, document

    def unavailable(self, request, location, member):
        messages.warning(request, _("Request a membership first: you sign the documents as part of it."))
        if location.enable_membership:
            return redirect('location-request-membership', slug=location.slug)
        return redirect('location-detail', slug=location.slug)

    def done_url(self, location, member, membership):
        # One document after the other, then back to the memberships page.
        following = member_documents.pending_online_documents(membership).first()
        if following is not None:
            return reverse('location-sign-document', kwargs={
                'slug': location.slug, 'document_uuid': following.uuid})
        return reverse('account-memberships')

    def cancel_url(self, location, member):
        return reverse('account-memberships')


class ManagerSignMembershipDocumentView(BaseSignView):
    """A manager hands their device to a member at the venue, who signs there."""
    in_person = True

    def resolve(self, request, slug, document_uuid, member_uuid=None):
        location = _managed_location(request, slug)
        document = get_object_or_404(
            MembershipDocument, uuid=document_uuid, location=location,
            kind=MembershipDocument.ONLINE, is_active=True)
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        return location, member, document

    def unavailable(self, request, location, member):
        messages.warning(request, _("Add a pending or active membership to this member before collecting signatures."))
        return redirect('location-member-detail', slug=location.slug, member_uuid=member.uuid)

    def done_url(self, location, member, membership):
        return reverse('location-member-detail', kwargs={'slug': location.slug, 'member_uuid': member.uuid})

    def cancel_url(self, location, member):
        return self.done_url(location, member, None)


class SignedDocumentView(LoginRequiredMixin, View):
    """A manager downloads (GET) or deletes (POST) a signed document of a member."""

    def _signed(self, request, slug, member_uuid, signed_uuid):
        location = _managed_location(request, slug)
        return get_object_or_404(
            SignedMembershipDocument.objects.select_related('member'),
            uuid=signed_uuid, member__uuid=member_uuid, member__location=location)

    def get(self, request, slug, member_uuid, signed_uuid):
        signed = self._signed(request, slug, member_uuid, signed_uuid)
        return _pdf_response(signed.pdf.open('rb'), member_documents.signed_pdf_filename(signed))

    def post(self, request, slug, member_uuid, signed_uuid):
        signed = self._signed(request, slug, member_uuid, signed_uuid)
        signed.pdf.delete(save=False)
        signed.delete()
        messages.success(request, _("Signed document deleted."))
        return redirect('location-member-detail', slug=slug, member_uuid=member_uuid)


class MySignedDocumentView(LoginRequiredMixin, View):
    """A member downloads their own copy of a document they signed."""

    def get(self, request, signed_uuid):
        signed = get_object_or_404(
            SignedMembershipDocument.objects.select_related('member'),
            uuid=signed_uuid, member__user_profile=request.user.user_profile)
        return _pdf_response(signed.pdf.open('rb'), member_documents.signed_pdf_filename(signed))
