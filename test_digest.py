import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import fetch_digest as d


class MorningEditionTests(unittest.TestCase):
    def test_rome_preparation_switch_in_winter_and_summer(self):
        for stamp, expected in [('2026-11-27T05:39:00+00:00','2026-11-26'),('2026-11-27T05:40:00+00:00','2026-11-27'),('2026-07-04T04:39:00+00:00','2026-07-03'),('2026-07-04T04:40:00+00:00','2026-07-04')]:
            self.assertEqual(str(d.edition_date(datetime.fromisoformat(stamp))),expected)

    def test_sections_do_not_treat_every_papa_as_pope(self):
        for title, expected in [('Il Papa riceve i vescovi del Perù','Vaticano'),('Papà porta il bambino a scuola','Società'),('Governo, intesa sulla manovra','Attualità'),('Ospedali e diritto alla salute','Società'),('Juventus, la vittoria in Champions',None)]:
            self.assertEqual(d.section_for({'title':title,'kind':'news'}),expected)
        self.assertIsNone(d.section_for({'title':'Il Papa riceve i vescovi','kind':'social'}))

    def test_freshness_deduplication_and_limit(self):
        now=datetime(2026,11,27,6,tzinfo=timezone.utc)
        def item(n,title,date='2026-11-27T05:00:00+00:00',**extra):
            return {'id':str(n),'title':title,'url':f'https://example.com/{n}','source':f'Source {n}','published':date,'kind':'news',**extra}
        items=[item(1,'Il Papa parla di pace'),item(2,'Il Papa parla di pace',cluster_id='same'),item(3,'Il Papa incontra i fedeli',cluster_id='same'),item(4,'Governo, intesa sulla manovra'),item(5,'Gli studenti tornano a scuola'),item(8,'Attacco con droni in Kuwait, morti due tecnici italiani'),item(9,'Tecnici italiani morti in Kuwait, la rabbia dei colleghi: Noi in guerra senza protezioni'),item(6,'Ministro parla in Parlamento','2026-11-25T05:00:00+00:00'),item(7,'Presidente parla dopo il vertice','2026-11-27T08:00:00+00:00')]
        groups=d.select_sections(items,now)
        all_items=[i for s in groups for i in s['items']]
        self.assertFalse({'6','7'} & {i['id'] for i in all_items})
        self.assertEqual(len([i for i in all_items if i['title']=='Il Papa parla di pace']),1)
        self.assertTrue(all(len(s['items'])<=3 for s in groups))
        self.assertEqual(sum('Kuwait' in i['title'] for i in all_items),1)
        self.assertEqual([s['title'] for s in groups],list(d.SECTIONS))

    def test_prepared_edition_is_not_replaced_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'digest.json'
            original={'editions':[{'date':'2026-11-27','sections':[],'available_at':'2026-11-27T07:00:00+01:00'}]}
            path.write_text(json.dumps(original))
            with patch.object(d,'OUT',path),patch.object(d,'read_feed') as reader:
                d.main(datetime(2026,11,27,12,tzinfo=timezone.utc))
                reader.assert_not_called()
            self.assertEqual(json.loads(path.read_text()),original)


if __name__=='__main__': unittest.main()
