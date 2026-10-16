import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core.research import store,investor_reviews as reviews

class BatchTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
  self.articles=[dict(id=str(n),sha256=str(n),title='Example news',text='Body',published_at='2026-10-13T00:00:00+00:00') for n in range(35)]
  self.evidence=patch.object(reviews.intel,'evidence',return_value=dict(company={'symbol':'EXAMPLE'},articles=self.articles,coverage=[],as_of=store.now()));self.evidence.start()
  self.docs=patch.object(reviews.articles,'read',side_effect=lambda a,**kw:dict(status='available',text='Entire body '+a['id'],response_sha256=a['sha256']));self.docs.start()
  self.calls=[]
 def tearDown(self):
  self.docs.stop();self.evidence.stop();self.data.stop();self.temp.cleanup()
 def batch(self,*args,article_ids,**kw):
  self.calls.extend(article_ids);identity=str(len(self.calls))
  store.write('investor/reviews/'+identity,dict(id=identity,as_of=store.now(),events=[],thesis_assessment=dict(status='unknown'),articles=[a for a in self.articles if a['id'] in article_ids],article_summaries=[dict(article_id=x) for x in article_ids],unknowns=[]))
  return dict(review_id=identity)
 def test_all_articles_batched_and_cached(self):
  with patch.object(reviews.intel,'interpret',side_effect=self.batch):
   r=reviews.interpret(None,'X');self.assertEqual(r['reviewed_articles'],35);self.assertEqual(r['batches'],4);self.assertEqual(len(set(self.calls)),35)
   self.assertTrue(reviews.interpret(None,'X')['cached']);self.assertEqual(len(self.calls),35)
 def test_failed_batch_remains_partial_and_retries(self):
  def batch(*args,**kw):
   if '10' in kw['article_ids']:raise ValueError('Invalid citations')
   return self.batch(*args,**kw)
  with patch.object(reviews.intel,'interpret',side_effect=batch):
   r=reviews.interpret(None,'X');self.assertTrue(r['partial']);self.assertEqual(r['reviewed_articles'],25)
   self.assertTrue(store.read('investor/latest/X')['failed_batches'])
   self.assertNotIn('cached',reviews.interpret(None,'X'))
 def test_unreadable_is_not_reviewed_or_neutral(self):
  self.docs.stop();self.docs=patch.object(reviews.articles,'read',return_value=dict(status='paywalled',reason='Blocked'));self.docs.start()
  with patch.object(reviews.intel,'interpret',side_effect=AssertionError('No LLM input')):
   r=reviews.interpret(None,'X');self.assertEqual(r['status'],'unavailable');self.assertIsNone(store.read('investor/latest/X'))
