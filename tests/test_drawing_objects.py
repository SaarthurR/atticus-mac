"""Object strokes use the overlay boundary without apps or windows."""
import unittest
import json

import atticus


class ObjectStrokeTests(unittest.TestCase):
    def test_curved_filled_outline_and_detail_map_to_screen(self):
        outline = {'kind': 'path', 'curve': True, 'fill': True,
                   'points': [[20,40],[20,10],[80,10],[80,40],[80,70],[20,70],[20,40]]}
        detail = {'kind': 'path', 'points': [[30,40],[70,40]]}
        payload = {'steps': [{'screen': 1, 'say': 'The outline encloses the inner stroke.',
                              'shapes': [outline, detail]}]}
        mapping = {'1': {'frame': [-200,100,200,200], 'pixels': [100,100]}}
        result = atticus.drawing(payload, mapping)
        self.assertTrue(result['teaching'])
        shapes = result['steps'][0]['shapes']
        self.assertEqual(shapes[0]['points'], [[-160,180],[-160,120],[-40,120],[-40,180],
                                               [-40,240],[-160,240],[-160,180]])
        self.assertTrue(shapes[0]['curve']); self.assertTrue(shapes[0]['fill'])
        self.assertEqual(shapes[1]['points'], [[-140,180],[-60,180]])
        self.assertEqual(payload['steps'][0]['shapes'][0], outline)

    def test_generic_help_example_is_valid_and_encloses_detail(self):
        example = atticus.DRAW_HELP.split('Generic outline + detail example (place in clear screen space): ',1)[1].split('\n',1)[0]
        result = atticus.drawing(json.loads(example.rstrip('.')))
        outline, detail = result['steps'][0]['shapes']
        self.assertTrue(outline['curve']); self.assertTrue(outline['fill'])
        self.assertEqual(outline['points'][0], outline['points'][-1])
        self.assertEqual(detail['points'], [[130,160],[190,160]])
        self.assertIn('never an image card', atticus.DRAW_HELP)

    def test_curve_and_fill_limits(self):
        good = {'kind': 'path', 'curve': True, 'points': [[10,10]] * 64}
        self.assertEqual(atticus.drawing({'steps': [{'say':'Outline.', 'shapes':[good]}]})
                         ['steps'][0]['shapes'][0], good)
        bad = [dict(good, points=[[10,10]] * n) for n in (2,3,5,65,67)]
        bad += [dict(good, curve=v) for v in (1,'yes',None)]
        bad += [dict(good, fill='yes'), dict(good, kind='line'), dict(good, kind='arrow')]
        bad += [{'kind':'rect','rect':[1,2,3,4],'curve':False}]
        bad += [dict(good, points=[[float('nan'),10]] * 4),
                dict(good, points=[[True,10]] * 4)]
        for shape in bad:
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'say':'Outline.', 'shapes':[shape]}]})
        for n in (1,257):
            with self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'say':'Outline.', 'shapes':[
                    {'kind':'path','fill':True,'points':[[10,10]] * n}]}]})


if __name__ == '__main__':
    unittest.main()
