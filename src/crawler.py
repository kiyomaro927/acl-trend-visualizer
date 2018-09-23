"""Crawler for ACL Anthology."""
import multiprocessing
import os
import requests
import sys

from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
from io import StringIO


URL_FORMAT = "http://aclweb.org/anthology/P{year}-{ptype}{pid:03d}"


class Crawler(object):

    def __init__(self, years, ptypes):
        """

        :param years: a list of strings which indicate years to gather.
        :param ptypes: a string which indicates submission type ("l" (long), "s" (short), or "lt").

        """
        assert len(set(ptypes) - set("sl")) == 0, "Invalid ptypes were specified: %s" % ptypes
        self.params = [{"year": year, "ptype": ptype, "pid": pid}
                       for year in years.split(",") for ptype in ptypes for pid in range(1, 1000)]

    def search(self, words, tmp_dir="tmp", jobs=1):
        os.makedirs(tmp_dir, exist_ok=True)

        params = self._make_chunks(self.params, words, tmp_dir, jobs)
        with multiprocessing.Pool(processes=jobs) as pool:
            results = pool.starmap(self._search, params)

        return [item for subresults in results for item in subresults]

    def _search(self, params, words, tmp_dir):
        _results = []
        while params:
            param = params.pop(0)
            url = URL_FORMAT.format(
                year=param["year"],
                ptype=self._make_ptype(param["ptype"]),  # "l" -> 1, "s" -> 2
                pid=param["pid"])
            basename = os.path.basename(url)
            path_paper = os.path.join(tmp_dir, basename)
            ok = self._save_paper(url, path_paper)
            if ok == 0:  # success
                _results.append({
                    "url": url,
                    "year": param["year"],
                    "ptype": param["ptype"],
                    "pid": param["pid"],
                    "words": self._check_words(words, path_paper)})
                self._delete_paper(path_paper)
            elif ok == 1:  # 404
                while True:  # delete queues which has greater pids
                    next_param = params[0]
                    if next_param["year"] == param["year"] \
                            and next_param["ptype"] == param["ptype"] \
                            and next_param["pid"] > param["pid"]:
                        params.pop(0)
                        if len(params) == 0:
                            return _results
                    else:
                        break
            else:  # something wrong
                continue
        return _results

    def _check_words(self, words, path):

        def build_ngram(l, n):
            return [' '.join(ngram) for ngram in list(zip(*(l[i:] for i in range(n))))]

        def convert_pdf_to_text(_path):
            with open(_path, "rb") as f:
                resource_manager = PDFResourceManager()
                outfp = StringIO()
                codec = "utf-8"
                laparams = LAParams()
                laparams.all_texts = True
                device = TextConverter(resource_manager, outfp, codec=codec, laparams=laparams)
                interpreter = PDFPageInterpreter(resource_manager, device)
                for page in PDFPage.get_pages(f):
                    interpreter.process_page(page)
                return self._clean_text(outfp.getvalue())

        try:
            ptext = convert_pdf_to_text(path)
        except Exception as e:
            print(e, file=sys.stderr)
            ptext = ""

        pword_list = ptext.split()
        return [word for word in words if word in build_ngram(pword_list, len(word.split()))]

    @staticmethod
    def _clean_text(text):
        return text.replace("-\n", "").replace("\n", " ").lower()

    @staticmethod
    def _save_paper(url, path):
        print("Downloading", url, file=sys.stderr)
        try:
            r = requests.get(url)
        except requests.RequestException as e:
            print(e, file=sys.stderr)
            return 2

        if r.url == "https://www.aclweb.org/404.shtml":
            print("Status Code: 404", file=sys.stderr)
            return 1
        elif r.status_code == 200:
            with open(path, "wb") as f:
                f.write(r.content)
            return 0
        else:
            print("Status Code:", r.status_code, file=sys.stderr)
            return 2

    @staticmethod
    def _delete_paper(path):
        if os.path.exists(path) is True:
            os.remove(path)

    @staticmethod
    def _make_ptype(ptype):
        if ptype == "l":
            return "1"
        elif ptype == "s":
            return "2"

    @staticmethod
    def _make_chunks(params, words, tmp_dir, n):
        if n < 1:
            print("Invalid parallelism.")
            sys.exit(1)
        n_chunk = len(params) // n
        return [(params[i:n_chunk+i], words, tmp_dir) for i in range(0, len(params), n_chunk)]
