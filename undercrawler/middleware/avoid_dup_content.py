import logging, time

from scrapy.http.response.text import TextResponse
from scrapy.exceptions import IgnoreRequest, NotConfigured

from ..dupe_predict import DupePredictor
from ..utils import extract_text


logger = logging.getLogger(__name__)


class AvoidDupContentMiddleware:
    '''
    Avoid requests for duplicate content. During crawling this middleware
    learns what parameters are important (influence content), and what can
    be safely ignored. Once it is confident it can start dropping
    (or de-prioritizing) requests that are unlikely to get new content.
    Requests with "skip_avoid_dup_content" in meta will be completely ignored.

    Required settings:
    AVOID_DUP_CONTENT_ENABLED = True
    '''
    def __init__(self):
        self.dupe_predictor = None
        # We initialize dupe detector only after gathering enough pages,
        # it needs them for better duplicate detection, to know which content
        # is common to a lot of pages, and which is unique.
        self.initial_queue = []  # (url, text)
        self.initial_queue_limit = 300

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool('AVOID_DUP_CONTENT_ENABLED'):
            raise NotConfigured
        return cls()

    def process_request(self, request, spider):
        if not self.dupe_predictor or self.skip(request):
            return
        url = request.url
        t0 = time.time()
        dupe_prob = self.dupe_predictor.get_dupe_prob(url)
        t = time.time() - t0
        if t > 0.01:
            logger.debug('get_dupe_prob took %.4f s for %s', t, url)
        # TODO - lower priority for some requests
        if dupe_prob > 0.98:
            logger.debug('Ignoring a likely duplicate %s with prob %.3f',
                            url, dupe_prob)
            raise IgnoreRequest

    def process_response(self, request, response, spider):
        if not hasattr(response, 'xpath') or self.skip(request):
            return response
        url, text = response.url, extract_text(response)
        t0 = time.time()
        if self.dupe_predictor:
            self.dupe_predictor.update_model(url, text)
            t = time.time() - t0
            if t > 0.01:
                logger.debug('Updated model in %.4f s for %s', t, url)
        else:
            self.initial_queue.append((url, text))
            if len(self.initial_queue) >= self.initial_queue_limit:
                logger.debug(
                    'Gathered enough intitial pages, building DupePredictor')
                self.dupe_predictor = DupePredictor(
                    texts_sample=[text for _, text in self.initial_queue])
                # Update model with all the pages we have missed
                for url, text in self.initial_queue:
                    self.dupe_predictor.update_model(url, text)
                self.initial_queue = None
                logger.debug('Built DupePredictor in %.4f s', time.time() - t0)
        return response

    def skip(self, request):
        return bool(request.meta.get('skip_avoid_dup_content'))
