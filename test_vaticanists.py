import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import vaticanist_authors as v


class AttributionTests(unittest.TestCase):
    def test_whole_bylines_and_accents(self):
        self.assertEqual(v.match_bylines(['By Edgar Beltran'])[0]['name'], 'Edgar Beltrán')
        self.assertEqual(v.match_bylines(['Joshua McElwee'])[0]['name'], 'Joshua Mc Elwee')
        self.assertEqual(len(v.match_bylines(['Gian Guido Vecchi; Manuela Tulli'])), 2)

    def test_mentions_are_not_bylines(self):
        self.assertFalse(v.match_bylines(['Interview with Manuela Tulli']))
        self.assertFalse(v.match_bylines(['ANSA']))
        self.assertFalse(v.article_bylines('<p>Manuela Tulli reports from Vatican</p>', 'https://example.com/a'))

    def test_recommendations_and_publisher_are_not_author(self):
        page='<script type="application/ld+json">'+json.dumps([
            {'@type':'NewsArticle','url':'https://example.com/a','author':{'name':'Unlisted Person'},'publisher':{'name':'Manuela Tulli'}},
            {'@type':'NewsArticle','url':'https://example.com/other','author':{'name':'Edgar Beltrán'}}
        ])+'</script>'
        self.assertEqual(v.article_bylines(page,'https://example.com/a'), ['Unlisted Person'])

    def test_canonical_and_meta(self):
        page='<link rel="canonical" href="https://example.com/a"><meta name="author" content="Manuela Tulli"><script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','url':'https://example.com/a','author':[{'name':'Edgar Beltrán'}]})+'</script>'
        self.assertEqual(v.article_bylines(page,'https://example.com/amp/a'), ['Manuela Tulli','Edgar Beltrán'])

    def test_failure_budget_cache_and_social(self):
        now=datetime.now(timezone.utc)
        items=[{'kind':'news','url':f'https://example.com/{i}','published':now.isoformat()} for i in range(5)]
        items.append({'kind':'social','url':'https://x.com/abc/status/1','author':'Manuela Tulli','published':now.isoformat()})
        with tempfile.TemporaryDirectory() as tmp, patch.object(v,'BYLINE_CACHE',Path(tmp)/'cache.json'), patch.object(v,'resolve_byline',return_value={}) as resolve:
            v.enrich_vaticanists(items,limit=2,now=now)
            self.assertEqual(resolve.call_count,2)
            v.enrich_vaticanists(items,limit=2,now=now)
            self.assertEqual(resolve.call_count,4)
            self.assertNotIn('vaticanist_ids',items[-1])

    def test_rotate_through_entire_roster(self):
        names=set()
        for i in range(8):
            now=datetime.fromtimestamp(600*i,timezone.utc)
            for query,_ in v.author_searches(now):
                for p in v.ROSTER:
                    if '"'+p['aliases'][-1]+'"' in query:
                        names.add(p['id'])
        self.assertEqual(len(names),314)


if __name__=='__main__': unittest.main()
