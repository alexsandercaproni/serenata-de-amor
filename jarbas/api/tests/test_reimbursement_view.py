from json import loads
from unittest.mock import patch
from urllib.parse import urlencode

from django.shortcuts import resolve_url
from django.test import TestCase
from freezegun import freeze_time
from mixer.backend.django import mixer

from jarbas.core.models import Reimbursement


def get_reimbursement(**kwargs):
    quantity = kwargs.pop('quantity', 1)
    kwargs['net_values'] = '1.99,2.99'
    kwargs['reimbursement_values'] = '200.00,500.00'
    kwargs['reimbursement_numbers'] = '2,3'
    if quantity == 1:
        return mixer.blend(Reimbursement, **kwargs)
    return mixer.cycle(quantity).blend(Reimbursement, **kwargs)


class TestListApi(TestCase):

    def setUp(self):
        get_reimbursement(quantity=3)
        self.url = resolve_url('api:reimbursement-list')

    def test_status(self):
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_content_general(self):
        self.assertEqual(3, Reimbursement.objects.count())
        self.assertEqual(3, self._count_results(self.url))

    def test_ordering(self):
        resp = self.client.get(self.url)
        content = loads(resp.content.decode('utf-8'))
        first = content['results'][0]
        last = content['results'][-1]
        self.assertEqual(3, len(content['results']))
        self.assertTrue(first['issue_date'] > last['issue_date'])

    def test_content_with_cnpj_cpf_filter(self):
        search_data = (
            ('cnpj_cpf', '12345678901'),
            ('subquota_id', '22'),
            ('order_by', 'probability'),
            ('suspicious', '1'),
        )
        url = '{}?{}'.format(self.url, urlencode(search_data))
        target_result = get_reimbursement(cnpj_cpf='12345678901', subquota_id=22, suspicious=1)
        resp = self.client.get(url)
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(1, len(content['results']))
        self.assertEqual(target_result.cnpj_cpf, content['results'][0]['cnpj_cpf'])

    def test_content_with_date_filters(self):
        get_reimbursement(issue_date='1970-01-01')
        get_reimbursement(issue_date='1970-01-01')
        search_data = (
            ('issue_date_start', '1970-01-01'),
            ('issue_date_end', '1970-02-02'),
        )
        url = '{}?{}'.format(self.url, urlencode(search_data))
        resp = self.client.get(url)
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(2, len(content['results']))

    def test_more_than_one_document_query(self):
        get_reimbursement(quantity=4, document_id=(id for id in (42, 84, 126, 168)))
        url = self.url + '?document_id=42,84+126,+168'
        resp = self.client.get(url)
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(4, len(content['results']))

    def _count_results(self, url):
        resp = self.client.get(url)
        content = loads(resp.content.decode('utf-8'))
        return len(content.get('results', 0))


@freeze_time('1970-01-01 00:00:00')
class TestRetrieveApi(TestCase):

    def setUp(self):
        self.reimbursement = get_reimbursement()
        url = resolve_url('api:reimbursement-detail',
                          document_id=self.reimbursement.document_id)
        self.resp = self.client.get(url)
        self.maxDiff = 2 ** 11

    def test_status(self):
        self.assertEqual(200, self.resp.status_code)

    def test_contents(self):
        contents = loads(self.resp.content.decode('utf-8'))
        for result_attr, result_value in contents.items():
            if not hasattr(self.reimbursement, result_attr):
                continue
            expected_value = getattr(self.reimbursement, result_attr)
            self.assertEqual(str(result_value), str(expected_value))


class TestReceiptApi(TestCase):

    def setUp(self):
        self.reimbursement = get_reimbursement(
            year=2017,
            applicant_id=1,
            document_id=20,
            receipt_url='http://www.camara.gov.br/cota-parlamentar/documentos/publ/1/2017/20.pdf'
        )
        self.reimbursement_no_receipt = get_reimbursement(receipt_url=None)
        self.url = resolve_url(
            'api:reimbursement-receipt', document_id=self.reimbursement.document_id)
        self.url_no_receipt = resolve_url(
            'api:reimbursement-receipt', document_id=self.reimbursement_no_receipt.document_id)

    @patch('jarbas.core.models.head')
    def test_fetch_existing_receipt(self, mocked_head):
        mocked_head.return_value.status_code = 200
        resp = self.client.get(self.url)
        expected = dict(url=self.reimbursement.receipt_url)
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(expected, content)

    @patch('jarbas.core.models.head')
    def test_fetch_non_existing_receipt(self, mocked_head):
        mocked_head.return_value.status_code = 404
        resp = self.client.get(self.url_no_receipt)
        expected = dict(url=None)
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(expected, content)

    @patch('jarbas.core.models.head')
    def test_refetch_existing_receipt(self, mocked_head):
        expected = dict(url=self.reimbursement.receipt_url)
        self.reimbursement.receipt_fetched = True
        self.reimbursement.receipt_url = None
        self.reimbursement.save()
        mocked_head.return_value.status_code = 200
        resp = self.client.get(self.url + '?force')
        content = loads(resp.content.decode('utf-8'))
        self.assertEqual(expected, content)
