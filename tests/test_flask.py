"""
!!! IMPORTANT:
Before running this test, you need to run both flask server and celery
"""

import requests
import json
import logging
import base64
import os
import unittest
import shutil
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import Verdict
from core.case import Case
from tests.test_base import TestBase
from config.config import SUB_BASE


class FlaskTest(TestBase):

    def setUp(self):
        self.workspace = '/tmp/flask'
        self.url_base = 'http://localhost:5000'
        self.token = ('ejudge', 'naive') # Token has to be reset to do this test
        super().setUp()

    def test_upload_success(self):
        fingerprint = 'test_%s' % self.rand_str()
        result = requests.post(self.url_base + '/upload/case/%s/input' % fingerprint, data=b'123123',
                               auth=self.token).json()
        self.assertEqual(result['status'], 'received')
        result = requests.post(self.url_base + '/upload/case/%s/output' % fingerprint, data=b'456456',
                               auth=self.token).json()
        self.assertEqual(result['status'], 'received')
        case = Case(fingerprint)
        case.check_validity()
        with open(case.input_file, 'r') as f1:
            self.assertEqual(f1.read(), '123123')
        with open(case.output_file, 'r') as f2:
            self.assertEqual(f2.read(), '456456')

    def test_upload_fail(self):
        fingerprint = 'test_%s' % self.rand_str()
        result = requests.post(self.url_base + '/upload/case/%s/input' % fingerprint, data=b'123123',
                               auth=('123', '345')).json()
        self.assertEqual(result['status'], 'reject')

    def test_delete_case(self):
        fingerprint = 'test_%s' % self.rand_str()
        result = requests.post(self.url_base + '/upload/case/%s/input' % fingerprint, data=b'123123',
                               auth=self.token).json()
        self.assertEqual(result['status'], 'received')
        result = requests.delete(self.url_base + '/delete/case/%s' % fingerprint, data=b'123123',
                                auth=self.token).json()
        self.assertEqual(result['status'], 'received')

    def test_upload_checker_fail(self):
        fingerprint = 'test_%s' % self.rand_str()
        json_data = {'fingerprint': fingerprint, 'code': 'code', 'lang': 'cpp'}
        result = requests.post(self.url_base + '/upload/checker', json=json_data,
                               auth=self.token).json()
        self.assertEqual('reject', result['status'])
        self.assertIn("CompileError", result['message'])

    def test_upload_interactor_with_delete(self):
        fingerprint = 'test_%s' % self.rand_str()
        json_data = {'fingerprint': fingerprint, 'code': self.read_content('./interact/interactor-a-plus-b.cpp', 'r'), 'lang': 'cpp'}
        result = requests.post(self.url_base + '/upload/checker', json=json_data,
                               auth=self.token).json()
        self.assertEqual('received', result['status'])
        self.assertIn(fingerprint, os.listdir(SUB_BASE))
        # without token
        result = requests.delete(self.url_base + '/delete/interactor/' + fingerprint).json()
        self.assertEqual('reject', result['status'])
        # wrong place
        result = requests.delete(self.url_base + '/delete/checker/' + fingerprint).json()
        self.assertEqual('reject', result['status'])
        result = requests.delete(self.url_base + '/delete/interactor/' + fingerprint, auth=self.token).json()
        self.assertEqual('received', result['status'])
        self.assertNotIn(fingerprint, os.listdir(SUB_BASE))

    def judge_aplusb(self, code, lang, hold=True):
        checker_fingerprint = self.rand_str(True)
        case_fingerprints = [self.rand_str(True) for _ in range(31)]
        checker_dict = dict(fingerprint=checker_fingerprint, lang='cpp', code=self.read_content('./submission/ncmp.cpp'))
        response = requests.post(self.url_base + "/upload/checker",
                                 json=checker_dict, auth=self.token).json()
        self.assertEqual(response['status'], 'received')

        for i, fingerprint in enumerate(case_fingerprints):
            response = requests.post(self.url_base + '/upload/case/%s/input' % fingerprint,
                                     data=self.read_content('./data/aplusb/ex_input%d.txt' % (i + 1), 'rb'),
                                     auth=self.token)
            self.assertEqual(response.json()['status'], 'received')
            requests.post(self.url_base + '/upload/case/%s/output' % fingerprint,
                          data=self.read_content('./data/aplusb/ex_output%d.txt' % (i + 1), 'rb'),
                          auth=self.token)
        judge_upload = dict(fingerprint=self.rand_str(True), lang=lang, code=code,
                            cases=case_fingerprints, max_time=1, max_memory=128, checker=checker_fingerprint,
                            )

        if not hold:
            judge_upload.update(hold=False)
            response = requests.post(self.url_base + '/judge', json=judge_upload, auth=self.token).json()
            self.assertEqual('received', response['status'])
            time.sleep(10)
            result = requests.get(self.url_base + '/query', json={'fingerprint': judge_upload['fingerprint']},
                                  auth=self.token).json()
            report = requests.get(self.url_base + '/query/report', json={'fingerprint': judge_upload['fingerprint']},
                                  auth=self.token).text
            logging.warning(report)
        else:
            result = requests.post(self.url_base + '/judge', json=judge_upload,
                                   auth=self.token).json()
        logging.warning(result)
        return result['verdict']

    def test_aplusb_judge(self):
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb.cpp'), 'cpp'), Verdict.ACCEPTED.value)
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb.cpp'), 'cpp', False), Verdict.ACCEPTED.value)
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb2.cpp'), 'cpp', False),
                         Verdict.ACCEPTED.value)

    def test_aplusb_judge_traceback(self):
        judge_upload = dict(fingerprint=self.rand_str(True), lang='cpp', code='',
                            cases=[], max_time=1, max_memory=128, checker='ttt', hold=False)
        response = requests.post(self.url_base + '/judge', json=judge_upload, auth=self.token).json()
        self.assertEqual('received', response['status'], response)
        time.sleep(3)
        response = requests.get(self.url_base + '/query', json={'fingerprint': judge_upload['fingerprint']},
                                auth=self.token).json()
        self.assertEqual('reject', response['status'])
        self.assertIn('message', response)

    def test_aplusb_judge_ce(self):
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb-ce.c'), 'c'),
                         Verdict.COMPILE_ERROR.value)
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb-ce.c'), 'c', False),
                         Verdict.COMPILE_ERROR.value)

    def test_aplusb_judge_wa(self):
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb-wrong.py'), 'python'),
                         Verdict.WRONG_ANSWER.value)
        self.assertEqual(self.judge_aplusb(self.read_content('./submission/aplusb-wrong.py'), 'python', False),
                         Verdict.WRONG_ANSWER.value)


if __name__ == '__main__':
    unittest.main()