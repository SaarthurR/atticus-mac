"""Screen drawing boundaries and coordinate mapping; native windows run only through the VM runner."""
from tests.test_drawing_math_page import HIS_CARD, MATH_STUB
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import scratch_dir, swift_motion
import atticus

ROOT = Path(__file__).resolve().parents[1]


class DrawingTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)

    def test_shapes_and_ax_anchors(self):
        shapes = [{'kind':k,'rect':[10,20,30,40]} for k in ('rect','circle')]
        shapes += [{'kind':k,'points':[[10,20],[30,40]]} for k in ('line','arrow','path')]
        shapes += [{'kind':'label','at':[10,20],'text':'Leg B'},{'kind':'pointer','at':[20,30]}]
        payload = {'steps':[{'id':'teach','shapes':shapes,'say':'This is the side.'}]}
        self.assertEqual(len(atticus.drawing(payload)['steps'][0]['shapes']),7)
        anchored = {'steps':[{'target':'Exact control','wait':True,'shapes':[{'kind':'rect'},{'kind':'pointer'},{'kind':'label','text':'Here'}]}]}
        self.assertEqual(atticus.drawing(anchored)['steps'][0]['target'],'Exact control')

    def test_circle_corner_order_does_not_change_the_ring(self):
        forward = atticus.parse_draw('[DRAW:circle 100,100 500,500]')
        reverse = atticus.parse_draw('[DRAW:circle 500,500 100,100]')
        self.assertEqual(reverse, forward)
        self.assertEqual(atticus.parse_draw('[DRAW:circle 300,210 40]')['shapes'][0]['rect'], [260,170,80,80])

    def test_inline_tags_parse_like_plip(self):
        p = atticus.parse_draw
        self.assertEqual(p('[DRAW:circle 300,210 40 green:the hypotenuse]'), {'screen':None,'shapes':[
            {'kind':'circle','rect':[260.0,170.0,80.0,80.0],'color':'green'},{'kind':'label','at':[340.0,210.0],'text':'the hypotenuse','color':'green'}]})
        self.assertEqual(p('[DRAW:circle 315,480:screen2 16 purple:right angle]')['screen'], 2)   # Plip: the screen often comes right after the points
        self.assertEqual(p('[DRAW:circle 315,480:screen2 16 purple:right angle]')['shapes'][0]['color'], 'yellow')   # Atticus's own colors
        self.assertEqual(p('[DRAW:circle 361,403 47,12:x]')['shapes'][0]['rect'], [47.0,12.0,314.0,391.0])   # two corners, in either order
        self.assertEqual(p('[DRAW:curve 1,2 3,4 5,6 :screen1]')['shapes'], [{'kind':'path','points':[[1.0,2.0],[3.0,4.0],[5.0,6.0]],'color':'blue','smooth':True}])
        self.assertEqual(p('[DRAW:arrow 1,1 5,5 9,1 red]')['shapes'][-1], {'kind':'arrow','points':[[5.0,5.0],[9.0,1.0]],'color':'red'})
        self.assertEqual(p('[DRAW:text 20,390:$x^2-3x+2$]')['shapes'], [{'kind':'text','at':[20.0,390.0],'text':'$x^2-3x+2$'}])
        tex = r'[DRAW:text 20,390:$\frac{a[i]}{b[j]}$]'
        self.assertEqual(atticus._draw_end(tex), len(tex))
        self.assertEqual(p(tex)['shapes'][0]['text'], r'$\frac{a[i]}{b[j]}$')
        self.assertEqual(p('[DRAW:highlight 66,136 215,157:purple]')['shapes'], [{'kind':'rect','rect':[66.0,136.0,149.0,21.0],'color':'yellow','fill':True}])
        for style in ('blue', 'yellow', 'green', 'red', 'white', 'purple'):
            shapes = p(f'[DRAW:arrow 100,100 300,200:{style}: Search]')['shapes']
            self.assertEqual(shapes[-1]['text'], 'Search')
            self.assertEqual(shapes[-1]['color'], atticus._DRAW_TONES[style])
        self.assertEqual(p('[DRAW:text 100,100:Blue whale]')['shapes'][0]['text'], 'Blue whale')
        self.assertEqual(p('[DRAW:text 100,100:Search: filters]')['shapes'][0]['text'], 'Search: filters')
        self.assertEqual(atticus.drawing({'steps':[{'say':'A label.', 'shapes':[{'kind':'label','at':[100,100],'text':'blue: notes','color':'blue'}]}]})['steps'][0]['shapes'][0]['text'], 'blue: notes')
        self.assertEqual(p('[DRAW:line 10,10 200,10 dashed:h]')['shapes'][0], {'kind':'line','points':[[10.0,10.0],[200.0,10.0]],'color':'blue','dashed':True})
        self.assertNotIn('dashed', p('[DRAW:line 10,10 200,10 dashed:h]')['shapes'][1])
        self.assertTrue(p('[DRAW:circle 300,210 40:helper dashed]')['shapes'][0]['dashed'])
        self.assertNotIn('dashed', p('[DRAW:highlight 66,136 215,157 dashed]')['shapes'][0])
        square = p('[DRAW:angle 100,100 200,100 100,0:right angle]')['shapes']   # Plip: a right angle is a little square, its name dropped
        self.assertEqual(len(square), 1); self.assertNotIn('smooth', square[0]); self.assertEqual(len(square[0]['points']), 3)
        self.assertEqual([round(v, 6) for v in square[0]['points'][1]], [121.6, 78.4])
        arc = p('[DRAW:angle 100,100 200,100 150,60:θ]')['shapes']
        self.assertTrue(arc[0]['smooth']); self.assertEqual(arc[1]['text'], 'θ')
        self.assertGreaterEqual(math.dist(arc[0]['points'][0], [100, 100]), 22)   # Plip's arc radius: 22-48, opened out when narrow
        self.assertIn('[DRAW:circle 420,180 40 yellow:Sun]', atticus.DRAWING)   # Plip's worked example: style goes before the colon
        self.assertEqual(atticus.drawing({'steps':[{'say':'A helper.','shapes':[{'kind':'line','points':[[1,1],[9,9]],'dashed':True}]}]})['steps'][0]['shapes'][0]['dashed'], True)
        with self.assertRaises(ValueError): atticus.drawing({'steps':[{'say':'A helper.','shapes':[{'kind':'label','at':[1,1],'text':'x','dashed':True}]}]})
        self.assertEqual(p('[DRAW:clear]'), 'clear')
        for bad in ('[DRAW:hexagon 1,1]', '[DRAW:arrow 1,1]', '[DRAW:text 1,1]', '[DRAW:]', 'DRAW:dot 1,1'):
            with self.subTest(bad=bad): self.assertIsNone(p(bad))
        self.assertEqual(atticus._draw_end('[DRAW:text 1,1:arr[i]] Next'), 22)
        self.assertIsNone(atticus._draw_end('[DRAW:text 1,1:[0, 1) on'))
        self.assertEqual(atticus._draw_end('[DRAW:text 1,1:[0, 1)] ' + 'x' * 61), 22)   # an unclosed label ends once the speech after it arrives

    def test_inline_steps_come_out_with_their_sentences(self):
        (self.root/'draw-screens.json').write_text(json.dumps({'screens':{
            '1':{'frame':[0,0,1440,900],'pixels':[1280,800],'name':'Built-in'},'2':{'frame':[1440,0,2560,1440],'pixels':[1280,720],'name':'LG'}},
            'target':{'pid':1,'windowID':'2','windowFrame':[0,0,10,10]}}))
        reply = ("Here's the graph. [DRAW:line 100,600 1200,600 white:x] [DRAW:line 640,700 640,50 white:y] These are the axes. "
                 "[DRAW:curve 400,100 640,600 880,100:y = x^2] It opens up. Done. [DRAW:dot 99999,1] Off the picture.")
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root),'ATTICUS_SCREEN':'LG'}):
            for step in (1, 5, 40):
                stream, events, shown = atticus.InlineDrawing(), [], []
                for i in range(1, len(reply) + 1, step):
                    text, out = stream.feed(reply[:i]); events += out; shown.append(text)
                    self.assertNotIn('[', text)   # a tag never shows, even half arrived
                text, out = stream.feed(reply, final=True); events += out
                with self.subTest(step=step):
                    self.assertEqual(text, "Here's the graph. \n These are the axes. \n It opens up. Done. \n Off the picture.")
                    news = [(before, len(payload['steps'])) for before, payload in events if before is not None]
                    self.assertEqual(news, [("Here's the graph. \n", 1), ("Here's the graph. \n These are the axes. \n", 2)])   # each step after the text before it
                    last = events[-1][1]
                    self.assertEqual([s['say'] for s in last['steps']], ['These are the axes.', 'It opens up. Done.'])
                    self.assertEqual(len(last['steps'][0]['shapes']), 4)   # tags with only space between them are one step
                    self.assertEqual(last['steps'][0]['shapes'][0]['points'], [[1640.0, 1200.0], [3840.0, 1200.0]])   # the Request screen's picture pixels
                    self.assertEqual((last['teaching'], last['target']['windowID'], len({p['guide'] for _, p in events})), (True, '2', 1))
                    self.assertFalse(any(text.endswith('These are the axes. \n It') for text in shown))   # a step's text waits for its sentence
            clear = atticus.InlineDrawing()
            _, out = clear.feed('[DRAW:dot 5,5] One. [DRAW:clear] [DRAW:dot 6,6] Two.', final=True)
            self.assertEqual([len(p['steps']) for _, p in out], [1])
            self.assertTrue(out[0][1]['guide'].endswith('-1'))   # after clear: a new guide, not step 2 of the old one
        self.assertEqual(atticus.InlineDrawing().feed('No drawing [here]. [DRAW', final=False), ('No drawing [here]. ', []))
        for text in ('Use arr[i] and [0, 1].', '```python\nvalues = [data[i] for i in ids]\n```', r'TeX: $[a,b]$ and \\[x\\].'):
            self.assertEqual(atticus.InlineDrawing().feed(text, final=True), (text, []))
        for text in ('Before. [DRAW', 'Before. [DRAW:text 1,1:never closes'):
            self.assertEqual(atticus.InlineDrawing().feed(text, final=True), ('Before. ', []))

    def test_inline_caption_keeps_the_reply_lines(self):
        (self.root/'draw-screens.json').write_text(json.dumps({'screens':{'1':{'frame':[0,0,1440,900],'pixels':[1440,900]}},
            'target':{'pid':1,'windowID':'2','windowFrame':[0,0,10,10]}}))
        reply = ('[DRAW:highlight 100,100 300,140] The channel has two videos:\n-   **"Bread basics"** pitches it.\n- **"Loaf"** is a demo.'
                 '\n\n\n\nDo you want   me to open it?')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)}):
            _, events = atticus.InlineDrawing().feed(reply, final=True)
        self.assertEqual(events[-1][1]['steps'][0]['say'],
                         'The channel has two videos:\n- **"Bread basics"** pitches it.\n- **"Loaf"** is a demo.\n\nDo you want me to open it?')
        messy = '[DRAW:highlight 100,100 300,140] ' + HIS_CARD.replace('\n- ', '\n-   ').replace('\n\n', '  \n\n\n\n')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)}):
            _, events = atticus.InlineDrawing().feed(messy, final=True)
        self.assertEqual(events[-1][1]['steps'][0]['say'], HIS_CARD)

    def test_inline_click_steps_wait_on_their_mark(self):
        (self.root/'draw-screens.json').write_text(json.dumps({'screens':{'1':{'frame':[0,0,1440,900],'pixels':[1440,900]}},
            'target':{'pid':1,'windowID':'2','windowFrame':[0,0,10,10]}}))
        reply = ('[DRAW:circle 1300,12 10 click:Menu icon] Open the menu. [DRAW:box 1100,40 1400,90] This tile shows the mode. '
                 '[DRAW:dot 1200,60 yellow click] Click the tile.')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)}):
            _, events = atticus.InlineDrawing().feed(reply, final=True)
        steps = events[-1][1]['steps']
        self.assertEqual([s.get('wait') for s in steps], [True, None, True])   # the model marks which steps wait, in the same reply
        self.assertEqual(steps[0]['hit'], [1280, 0, 40, 32])   # what the ring holds plus slack, kept on its display
        self.assertEqual(steps[2]['hit'], [1190, 50, 20, 20])
        self.assertNotIn('hit', steps[1])
        self.assertTrue(events[-1][1]['teaching'])
        self.assertNotIn('wait', atticus.parse_draw('[DRAW:circle 5,5 4 yellow:Look]'))

    def test_draw_cli_keeps_tex_backslashes_in_json(self):
        payload = json.dumps({'steps':[{'say':'Add $a\\;b$ \\ ok\n','shapes':[{'kind':'text','text':r'$\frac12$'}]}]}).replace(r'\\;', r'\;')
        with patch.object(atticus,'draw',return_value='Guide shown') as draw, patch('sys.argv',['atticus.py','--draw',payload]), patch('sys.stdout'):
            atticus.main()
        step = draw.call_args.args[0]['steps'][0]
        self.assertEqual((step['say'], step['shapes'][0]['text']), ('Add $a\\;b$ \\ ok\n', '$\\frac12$'))

    def test_draw_json_repair_keeps_valid_escapes_in_a_mixed_payload(self):
        for payload, expected in ((r'{"steps":[{"say":"first\nnext\tthen","shapes":[{"kind":"text","text":"$\;x$"}]}]}', 'first\nnext\tthen'),
                                  (r'{"steps":[{"say":"first\nnext\tthen","shapes":[]}]}', 'first\nnext\tthen')):
            with patch.object(atticus, 'draw', return_value='Guide shown') as draw, patch('sys.argv', ['atticus.py', '--draw', payload]), patch('sys.stdout'):
                atticus.main()
            self.assertEqual(draw.call_args.args[0]['steps'][0]['say'], expected)
        valid = r'{"steps":[{"say":"\frac\nnext\tthen\u03b1\\end\"","shapes":[]}]}'
        with patch.object(atticus, 'draw', return_value='Guide shown') as draw, patch('sys.argv', ['atticus.py', '--draw', valid]), patch('sys.stdout'):
            atticus.main()
        self.assertEqual(draw.call_args.args[0], json.loads(valid))

    def test_smooth_paths_keep_samples_and_reject_conflicting_modes(self):
        shape = {'kind':'path','smooth':True,'points':[[0,0],[50,100],[100,0]]}
        mapping = {'1':{'frame':[-200,0,200,200],'pixels':[100,100]}}
        got = atticus.drawing({'steps':[{'screen':1,'say':'A curve.','shapes':[shape]}]},mapping)
        self.assertEqual(got['steps'][0]['shapes'][0], {**shape,'points':[[-200,0],[-100,200],[0,0]]})
        for bad in ({**shape,'curve':True}, {**shape,'smooth':'yes'}, {**shape,'kind':'line'},
                    {**shape,'points':[[0,0]]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'say':'A curve.','shapes':[bad]}]})

    def test_large_text_lines_for_worked_math(self):
        mapping = {'2':{'frame':[-1920,0,1920,1080],'pixels':[1280,720]}}
        steps = [{'screen':2,'say':'Split the 12.','shapes':[{'kind':'text','text':'12x⁵ = (3·4)·x⁵','at':[640,360],'size':'l'}]},
                 {'say':'Check it.','shapes':[{'kind':'text','text':'3·4 = 12 ✓','color':'green'}]}]
        value = atticus.drawing({'steps':steps},mapping)
        self.assertEqual(value['steps'][0]['shapes'][0],{'kind':'text','text':'12x⁵ = (3·4)·x⁵','at':[-960,540],'size':'l'})
        self.assertTrue(value['teaching'])
        for bad in ({'kind':'text'},{'kind':'text','text':''},{'kind':'text','text':'x'*301},{'kind':'text','text':'a','size':'xl'},
                    {'kind':'text','text':'a','rect':[1,2,3,4]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})
        self.assertIn('text "text" (one large line',atticus.DRAW_HELP)
        self.assertIn('Drawings stay through later asks',atticus.DRAW_HELP)

    def test_filled_diagram_parts_and_sized_labels(self):
        shapes = [{'kind':'circle','rect':[100,100,300,220],'color':'green','fill':True},
                  {'kind':'rect','rect':[130,130,240,160],'color':'blue','fill':False},
                  {'kind':'label','at':[250,210],'text':'Cell membrane','size':'l'}]
        value = atticus.drawing({'steps':[{'say':'Compare the two layers.','shapes':shapes}]})
        self.assertEqual(value['steps'][0]['shapes'],shapes)
        self.assertIn('circle may be an ellipse; add "fill":true',atticus.DRAW_HELP)
        self.assertIn('optional "size":"s"|"m"|"l"',atticus.DRAW_HELP)
        for bad in ({'kind':'circle','rect':[1,2,3,4],'fill':'yes'},
                    {'kind':'line','points':[[1,2],[3,4]],'fill':True},
                    {'kind':'label','at':[1,2],'text':'x','size':'xl'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})

    def test_help_names_the_order_and_keys_the_validator_takes(self):
        help_ = atticus.DRAW_HELP
        self.assertLess(help_.index(atticus.LOOK),help_.index(atticus.DRAW + " '<JSON>'"))   # draw() refuses without this ask's --look
        for said in ('"size":"s"|"m"|"l"','"screen":N on the step (never in a shape)','(exactly 2; path for more)'): self.assertIn(said,help_)
        for bad in ({'kind':'text','text':'a','s':'l'},{'kind':'label','at':[1,1],'text':'a','screen':2},{'kind':'line','points':[[0,0],[1,1],[2,2]]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})

    def test_explain_asks_get_a_diagram_not_marks_on_words(self):
        help_ = atticus.DRAW_HELP   # Oct 20 "draw and explain cell wall vs membrane": two rects around the study guide's words
        self.assertIn('Pick the kind from the ask, not from what is on screen',help_)
        self.assertLess(help_.index('- Locate ('),help_.index('Fit the mark'),help_.index('- Explain ('))   # rect/circle fitting is for locating only
        for said in ('draw the idea itself','clear space','otherwise draw your own',"marks around on-screen words are not an explanation"): self.assertIn(said,help_)
        self.assertNotIn('build on the on-screen material',help_)
        mapping = {'2':{'frame':[1440,0,1920,1080],'pixels':[1280,720]}}   # the logged ask drew on screen 2 in --look pixels
        logged = {'steps':[{'id':'1','screen':2,'say':'The membrane…','shapes':[{'kind':'rect','rect':[626,484,270,16],'color':'blue'}]},
                           {'id':'2','screen':2,'say':'The cell wall…','shapes':[{'kind':'rect','rect':[702,509,88,15],'color':'green'}]}]}
        diagram = {'steps':[{'screen':2,'say':'Every cell has a thin, flexible membrane that picks what gets in.','shapes':[
                                {'kind':'circle','rect':[940,120,140,140],'color':'blue'},{'kind':'label','at':[960,280],'text':'membrane: every cell'}]},
                            {'screen':2,'say':'Plants, fungi and bacteria add a rigid wall outside it.','shapes':[
                                {'kind':'rect','rect':[1100,110,160,160],'color':'green'},{'kind':'circle','rect':[1115,125,130,130],'color':'blue'},
                                {'kind':'label','at':[1110,280],'text':'wall + membrane'},{'kind':'arrow','points':[[792,516],[1100,190]],'color':'green'}]},
                            {'screen':2,'say':'Side by side.','shapes':[{'kind':'text','text':'membrane: flexible gate, every cell','at':[940,330]},
                                {'kind':'text','text':'wall: rigid, outside, stops bursting'}]}]}
        for value in (logged,diagram): self.assertTrue(atticus.drawing(value,mapping)['teaching'])   # both valid: only the help tells them apart

    def test_explanation_captions_match_visible_geometry(self):
        whole = {'kind':'rect','rect':[100,100,180,180]}
        upper = {'kind':'rect','rect':[100,100,180,60],'color':'blue','fill':True}
        lower = {'kind':'rect','rect':[100,160,180,120],'color':'green','fill':True}
        payload = {'steps':[
            {'say':'The whole region is a square.','shapes':[whole]},
            {'say':'The upper region fills one third of the whole region; the lower region fills two thirds.',
             'shapes':[upper,lower,{'kind':'label','at':[300,130],'text':'upper region: 1/3'},
                       {'kind':'label','at':[300,220],'text':'lower region: 2/3'}]},
        ]}
        # Fixture oracle: named parts require geometry, not merely matching label text.
        required = [{'whole region':whole}, {'whole region':whole,'upper region':upper,'lower region':lower}]

        def validate(value):
            visible = []
            for step, parts in zip(atticus.drawing(value)['steps'], required):
                visible.extend(step['shapes'])
                for name, mark in parts.items():
                    self.assertIn(name,step['say'])
                    self.assertIn(mark,visible,f'Caption names {name} without its geometry')

        validate(payload)
        for mutation in ('missing','misplaced','label_only','future'):
            bad = copy.deepcopy(payload)
            shapes = bad['steps'][1]['shapes']
            if mutation == 'missing': shapes.pop(1)
            elif mutation == 'misplaced': shapes[1]['rect'][1] += 20
            elif mutation == 'label_only': shapes.pop(0); shapes.pop(0)
            else: bad['steps'].reverse()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(AssertionError,'without its geometry'):
                validate(bad)
        for rule in ('Each caption must describe marks already visible in that step',
                     'Labels and equations alone do not show a geometric relationship',
                     'Check positions, sizes, proportions and connections against the caption'):
            self.assertIn(rule,atticus.DRAW_HELP)

    def test_follow_up_sees_the_drawing_and_a_selected_mark(self):
        drawn = {'steps':[{'say':'The shared x.','shapes':[{'kind':'circle','rect':[600,170,60,60],'color':'red'}]}],'shown':1}
        context = atticus.drawing_context(drawn)
        self.assertIn('still on screen, step 1 of 1',context)
        self.assertIn('"rect":[600,170,60,60]',context)
        self.assertIn('A new drawing replaces it, so redraw the parts to keep.',context)
        for bad in (None,{},{'steps':[]},{'steps':'x'},'steps'):
            self.assertEqual(atticus.drawing_context(bad),'')
        many = {'steps':[{'say':f'Step {i}','shapes':[{'kind':'path','points':[[j,j] for j in range(256)]}]} for i in range(12)]}
        squeezed = atticus.drawing_context(many)
        self.assertIn('"Step 11"',squeezed); self.assertLess(len(squeezed),2300)
        with tempfile.NamedTemporaryFile(prefix='atticus-point-',suffix='.jpg') as image:
            value = {'bounds':[570,140,120,120],'path':[[594,164],[666,236]],'image':image.name,'element':'',
                     'mark':'circle in step 1 of 1: The shared x.'}
            context, shots = atticus.point_context(value)
        self.assertIn('User selected a mark of your drawing',context)
        self.assertIn('The shared x.',context)
        self.assertIn('selected this mark',shots[0][1])
        self.assertEqual(atticus.point_context({**value,'image':'/etc/hosts','mark':'circle'})[0][:30],'User selected a mark of your d')   # text alone still counts
        self.assertEqual(atticus.point_context({**value,'image':'/etc/hosts','mark':7})[0],'')

    def test_pointer_rejects_stale_or_off_picture_coordinates(self):
        displays = [('Laptop',0,0,1440,900,True),('Monitor',-1920,-180,1920,1080,False)]
        with patch.object(atticus,'screens',return_value=displays), patch.object(atticus,'say') as say:
            self.assertEqual(atticus.point('Here. [point 2 640 360]'),'Here.')
            say.assert_called_once_with('@','-960 360 answer')
            say.reset_mock()
            for tag in ('[point 3 20 30]','[point 2 1281 30]','[point 2 20 721]','[point 2 -1 20]','[point nope]'):
                with self.subTest(tag=tag):
                    self.assertEqual(atticus.point('Here. ' + tag),'Here.')
            say.assert_not_called()

    def test_bad_coordinates_and_unbounded_payloads_are_rejected(self):
        good = {'steps':[{'shapes':[{'kind':'rect','rect':[1,2,3,4]}]}]}
        for rect in ([0,0,0,1],[0,0,-2,1],[True,0,1,1],[float('nan'),0,1,1],[float('inf'),0,1,1],[100001,0,1,1],[0,0,1],'bad'):
            value = copy.deepcopy(good); value['steps'][0]['shapes'][0]['rect'] = rect
            with self.subTest(rect=rect), self.assertRaises(ValueError): atticus.drawing(value)
        for step in ({'shapes':[]},{'shapes':[{'kind':'html','text':'bad'}]},
                     {'shapes':[{'kind':'pointer'}]}, {'wait':True,'shapes':[{'kind':'rect','rect':[0,0,1,1]}]},
                     {'timeout':1000,'shapes':[{'kind':'rect','rect':[0,0,1,1]}]}):
            with self.subTest(step=step), self.assertRaises(ValueError): atticus.drawing({'steps':[step]})
        with self.assertRaises(ValueError): atticus.drawing({'steps':good['steps']*13})
        for kind in ('line','arrow','path'):
            with self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'shapes':[{'kind':kind,'points':[[1,2],[3,4]],'rect':[1]}]}]})

    def test_retina_scaled_and_non_retina_pixel_mapping(self):
        mapping = {'1':{'frame':[0,0,1440,900],'pixels':[2880,1800]},
                   '2':{'frame':[-1920,-180,1920,1080],'pixels':[1280,720]},
                   '3':{'frame':[1440,0,1920,1080],'pixels':[1920,1080]}}
        step = lambda n,p: {'screen':n,'say':'Look here.','shapes':[{'kind':'pointer','at':p}]}
        second = step(2,[640,360]); second['shapes'].append({'kind':'rect','rect':[0,0,1280,720]})
        result = atticus.drawing({'steps':[step(1,[1440,900]),second,step(3,[960,540])]},mapping)
        self.assertEqual(result['steps'][0]['shapes'][0]['at'],[720,450])
        self.assertEqual(result['steps'][1]['shapes'][0]['at'],[-960,360])
        self.assertEqual(result['steps'][1]['shapes'][1]['rect'],[-1920,-180,1920,1080])
        self.assertEqual(result['steps'][2]['shapes'][0]['at'],[2400,540])
        for pixel in ([-1,0],[1281,0],[0,721]):
            with self.assertRaises(ValueError): atticus.drawing({'steps':[step(2,pixel)]},mapping)
        with self.assertRaises(ValueError): atticus.drawing({'steps':[step(4,[0,0])]},mapping)

    def test_disabled_tool_and_prompt_budget(self):
        with patch.object(atticus,'pref',side_effect=lambda k,d: False if k == 'draw' else d):
            self.assertNotIn('--draw',atticus.system_prompt(atticus.ASK_FIRST,'sonnet'))
            self.assertNotIn('[DRAW:',atticus.system_prompt(atticus.ASK_FIRST,'sonnet'))
            with self.assertRaisesRegex(ValueError,'off'): atticus.draw({'steps':[]})
        installed = str(Path.home()/'Applications/Atticus.app/Contents/Resources/atticus.py')
        drawing = atticus.system_prompt(atticus.ASK_FIRST,'sonnet')
        self.assertIn('[DRAW:shape points style:label]',drawing)
        aloud = len(atticus.READ_ALOUD)   # read answers aloud is on by default (Nov 17, 2026)
        self.assertLessEqual(len(drawing.replace(atticus.ME,installed)),11500+85+aloud)   # the model that draws carries the tag grammar; +85: charts graph line
        prompt = atticus.system_prompt(atticus.ASK_FIRST)
        self.assertNotIn('[DRAW:',prompt)
        self.assertLessEqual(len(prompt.replace(atticus.ME,installed)),10050+aloud)   # +50 for the send-to-running-input rule (1.3.2)
        with patch.object(atticus,'routing_mode',return_value='balanced'):   # Haiku hands drawing asks on with [explain]
            balanced = atticus.system_prompt(atticus.ASK_FIRST,'haiku')
            self.assertNotIn('[DRAW:',balanced); self.assertNotIn(atticus.DRAW_TOOL,balanced)
        with patch.object(atticus,'routing_mode',return_value='cheapest'):   # nothing to hand on to: quick asks keep the old tool line and size
            cheapest = atticus.system_prompt(atticus.ASK_FIRST,'haiku')
            self.assertIn(atticus.DRAW_TOOL,cheapest); self.assertNotIn('[DRAW:',cheapest)
        print('Drawing review prompt chars:', {k:len(v.replace(atticus.ME,installed)) for k,v in
              [('cheapest',cheapest),('balanced',balanced),('drawing',drawing)]}, 'offer:',len(atticus.MODEL_OFFER))
        with patch.object(atticus,'client',return_value='pi'):   # Pi and Devin answers are read only at the end: they keep the tool
            self.assertIn('use --draw once on Request screen unless user names another',atticus.system_prompt(atticus.ASK_FIRST))
        self.assertIn('draw',atticus.switches())
        self.assertFalse(atticus.replayable(atticus.DRAW + " '{}'"))

    def test_prompt_shows_click_in_a_tag_for_a_step_they_do(self):
        tags = [t for t in re.findall(r'\[DRAW:[^\]]*\]',atticus.DRAWING) if re.search(r'\bclick\b',t)]
        self.assertTrue(tags)
        self.assertTrue(atticus.parse_draw(tags[0])['wait'])

    def test_confirmation_and_request_relay(self):
        data = {'steps':[{'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}
        target = {'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
        (self.root/'draw-screens.json').write_text(json.dumps({
            'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}}, 'target':target}))
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), \
             patch.object(atticus,'draw_target',return_value=target), patch.object(atticus,'emit') as emit:
            with patch.object(atticus,'wait_commit',return_value=False):
                with self.assertRaises(ValueError): atticus.draw(data)
            emit.assert_not_called()
            def shown(lines):
                Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
            emit.side_effect = shown
            with patch.object(atticus,'wait_commit',return_value=True):
                self.assertEqual(atticus.draw(data),'Guide shown (step 1 of 1). Leave it running.')
            value = json.loads(emit.call_args.args[0][0][2:])
            self.assertEqual(value['target'],target)
            self.assertEqual(value['state'],atticus.hands_state())
            self.assertTrue(value['teaching'])

    def test_draw_requires_fresh_screen_context(self):
        data = {'steps':[{'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), \
             patch.object(atticus,'wait_commit',return_value=True), patch.object(atticus,'emit') as emit, \
             patch.object(atticus,'draw_target') as target:
            with self.assertRaisesRegex(ValueError,'--look before drawing'):
                atticus.draw(data)
        emit.assert_not_called()
        target.assert_not_called()

    def test_failed_look_clears_old_drawing_snapshot(self):
        snapshot=self.root/'draw-screens.json';snapshot.write_text('{"screens":{"1":{"frame":[0,0,10,10],"pixels":[10,10]}}}')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False),patch.object(atticus,'screens',return_value=[]):
            self.assertEqual(atticus.look(cleanup=False),[])
        self.assertFalse(snapshot.exists())

    def test_look_falls_back_when_the_ask_folder_is_read_only(self):
        def run(args, **_):
            if args[1:2] == ['--look']: Path(args[-1]).write_bytes(b'x')
            return subprocess.CompletedProcess(args, 0, stdout='pixelWidth: 1280\npixelHeight: 800\n')
        ask = self.root/'ask'; ask.mkdir(); ask.chmod(0o500)
        self.addCleanup(ask.chmod, 0o700)
        with patch.dict(os.environ,{'ATTICUS_ASK':str(ask)}), patch.object(atticus,'pref',side_effect=lambda k,d: False if k == 'draw' else d), \
             patch.object(atticus,'screens',return_value=[('Laptop',0,0,1440,900,True)]), patch.object(atticus.subprocess,'run',run), \
             patch.object(atticus.atexit,'register') as register:
            shots = atticus.look()
        self.assertEqual(len(shots), 1)
        self.addCleanup(os.remove, shots[0][0])
        self.assertEqual(os.path.dirname(shots[0][0]), tempfile.gettempdir())
        register.assert_called_once()   # outside the ask folder nobody else removes it
        import threading
        asked = threading.Event()
        def target(): asked.set(); return {'windowID': '7'}
        def run(args, **_):
            if args[1:2] == ['--look']:
                assert asked.wait(2), 'the target lookup waited for the capture'
                Path(args[-1]).write_bytes(b'x'); return subprocess.CompletedProcess(args, 0)
            return subprocess.CompletedProcess(args, 0, stdout='pixelWidth: 1280\npixelHeight: 800\n')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), patch.object(atticus,'screens',return_value=[('Laptop',0,0,1440,900,True)]), \
             patch.object(atticus,'draw_target',target), patch.object(atticus.subprocess,'run',run):
            self.assertEqual(len(atticus.look(cleanup=False)), 1)
        snapshot = json.loads((self.root/'draw-screens.json').read_text())
        self.assertEqual((snapshot['target'], snapshot['screens']['1']['pixels']), ({'windowID': '7'}, [1280, 800]))

    def test_look_keeps_screen_mappings_when_target_lookup_fails(self):
        def run(args, **_):
            if args[1:2] == ['--look']:
                Path(args[-1]).write_bytes(b'x')
            return subprocess.CompletedProcess(args, 0, stdout='pixelWidth: 1280\npixelHeight: 800\n')
        for error in (ValueError('No visible target window'), subprocess.TimeoutExpired('target', 2), OSError('unavailable')):
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {'ATTICUS_ASK':str(self.root)}), \
                 patch.object(atticus, 'screens', return_value=[('Display',0,0,1440,900,True)]), \
                 patch.object(atticus, 'draw_target', side_effect=error), patch.object(atticus.subprocess, 'run', run):
                self.assertEqual(len(atticus.look(cleanup=False)), 1)
                snapshot = json.loads((self.root/'draw-screens.json').read_text())
                self.assertEqual(snapshot, {'screens':{'1':{'frame':[0,0,1440,900],'pixels':[1280,800],'name':'Display'}}, 'target':None})
                def shown(lines):
                    Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
                with patch.object(atticus, 'wait_commit', return_value=True), patch.object(atticus, 'emit', side_effect=shown) as emit:
                    self.assertIn('Guide shown', atticus.draw({'steps':[{'screen':1,'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}))
                    self.assertIsNone(json.loads(emit.call_args.args[0][0][2:])['target'])
                    with self.assertRaisesRegex(ValueError, '--look again'):
                        atticus.draw({'steps':[{'target':'Control','say':'Look here.','shapes':[{'kind':'rect'}]}]})

    def test_look_fails_closed_when_native_helper_is_missing(self):
        calls = []
        def run(args, **_):
            calls.append(args)
            if args[0] == atticus.APP:
                raise FileNotFoundError(2, 'missing helper', atticus.APP)
            return subprocess.CompletedProcess(args, 0, stdout='')
        window = {'windowID':'7', 'windowFrame':[0,0,800,600], 'window':'Hidden', 'app':'Example', 'visible':False}
        with patch.dict(os.environ, {'ATTICUS_ASK':str(self.root)}), \
             patch.object(atticus, 'pref', side_effect=lambda k,d: False if k == 'draw' else d), \
             patch.object(atticus, 'screens', return_value=[('Display',0,0,1440,900,True)]), \
             patch.object(atticus.subprocess, 'run', run):
            shots = atticus.look(cleanup=False, window=window)
        self.assertEqual(shots, [])  # plain screencapture cannot exclude the held/fading trail
        self.assertEqual([args[0] for args in calls], [atticus.APP])

    def test_ax_draw_refreshes_the_map_in_the_look_target(self):
        target={'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
        (self.root/'draw-screens.json').write_text(json.dumps({
            'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}},'target':target}))
        data={'steps':[{'target':'Send','wait':True,'shapes':[{'kind':'rect'}]}]}
        def shown(lines): Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False),patch.object(atticus,'wait_commit',return_value=True), \
             patch.object(atticus,'hands_map',return_value=target) as mapped,patch.object(atticus,'emit',side_effect=shown) as emit:
            self.assertIn('Guide shown',atticus.draw(data))
            mapped.assert_called_once_with(target=target)
            self.assertEqual(json.loads(emit.call_args.args[0][0][2:])['target'],target)
            mapped.reset_mock()
            (self.root/'draw-screens.json').write_text(json.dumps({
                'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}}}))
            with self.assertRaisesRegex(ValueError,'--look again'): atticus.draw(data)
            mapped.assert_not_called()

    def test_verified_guide_replaces_a_long_final_answer(self):
        long_answer = 'A long duplicate explanation that belongs in the guide.'
        self.assertEqual(atticus.guide_reply([{'error':False,'result':'Guide shown (step 1 of 4). Leave it running.'}],long_answer),
                         'Done. Steps are on screen.')
        self.assertEqual(atticus.guide_reply([{'error':True,'result':'Guide shown (step 1 of 4). Leave it running.'},
                                              {'error':False,'result':long_answer}],long_answer),long_answer)

    def test_teaching_steps_keep_order_and_visible_captions(self):
        data = {'steps':[
            {'id':'triangle','say':'Draw the right triangle.','shapes':[{'kind':'path','points':[[10,10],[10,80],[90,80],[10,10]]}]},
            {'id':'labels','say':'Label one side.','shapes':[{'kind':'label','at':[20,50],'text':'a'}]},
            {'id':'formula','say':'Now use a² + b² = c².','shapes':[{'kind':'label','at':[20,20],'text':'a² + b² = c²'}]},
            {'id':'example','say':'For 3 and 4, c is 5.','shapes':[{'kind':'label','at':[20,35],'text':'3² + 4² = 5²'}]},
        ]}
        value = atticus.drawing(data)
        self.assertTrue(value['teaching'])
        self.assertEqual([step['id'] for step in value['steps']],['triangle','labels','formula','example'])
        self.assertEqual([step['say'] for step in value['steps']],[step['say'] for step in data['steps']])
        with self.assertRaisesRegex(ValueError,'visible say caption'):
            atticus.drawing({'steps':[{'shapes':[{'kind':'pointer','at':[10,10]}]}]})

    def test_app_lifecycle_connects_to_clear(self):
        source = (ROOT/'Atticus.swift').read_text()
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        section = lambda start, end: app.split(start,1)[1].split(end,1)[0]
        self.assertIn('drawing.clear()',section('func close(clear: Bool)','\n    }'))   # the box's ✕ takes the drawing with it
        self.assertIn('unpoint(false)',section('func start(dictate: Bool, quiet: Bool = false)','func heard('))   # a voice ask clears the old answer ring at key-down
        for start,end in [('func hush()', 'func stopOfferInput()'),('func run(_ t:', '// MARK: - Agent panels'),('func typed(', 'func finish()')]:
            self.assertNotIn('drawing.clear()',section(start,end),start)   # a follow-up keeps the drawing; only a new one replaces it
        self.assertIn('drawing.clearInput(); drawing.deselect()',section('func run(_ t:', '// MARK: - Agent panels'))
        self.assertIn('if let drawn { request["drawing"] = drawn }',app)
        esc = section('func escape()','func hush()')
        self.assertLess(esc.index('} else if busy {'),esc.index('} else if drawing.active {'))   # Esc stops the answer first, then clears the drawing
        self.assertIn('app.drawing.clear()',source.split('func applicationShouldTerminate',1)[1].split('\n    }',1)[0])
        self.assertIn('!stuck, !drawing.active',app)
        self.assertIn('!mini.holds, !drawing.active',app)
        ask_finish = app.split('func spawn()',1)[1].split('func unwarm()',1)[0]
        self.assertNotIn('drawing.clear()',ask_finish)

    def test_follow_ups_keep_the_guide_display_and_voice_prewarms(self):
        source = (ROOT/'Atticus.swift').read_text()
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        start = app.split('func start(dictate: Bool, quiet: Bool = false)',1)[1].split('func heard(',1)[0]
        typed = app.split('func typed(',1)[1].split('func finish()',1)[0]
        finish = app.split('func finish()',1)[1].split('func spawn()',1)[0]
        self.assertIn('if !dictate && !drawingReply { targetScreen = currentRequestScreen(panel) }',start)
        self.assertIn('if !dictate && (!replying || drawingReply) { unwarm(); warm = spawn() }',start)
        self.assertIn('if !drawing.active { targetScreen = currentRequestScreen(panel) }',typed)
        self.assertIn('hush(keepReply: false, keepWarm: true); typed(response, heard: true)',finish)
        self.assertIn('if transcriptKey(response) == "next" { unwarm(); drawing.next()',finish)

    def test_guide_steps_callouts_and_voice_policy(self):
        source = (ROOT/'Atticus.swift').read_text()
        drawing = source.split('final class ScreenDrawing {',1)[1].split('// The box can take typing',1)[0]
        self.assertIn('earlier += r.steps[..<index].enumerated().map { view.render($0.element.shapes,animate:false,previous:nil,append:true,parts:parts,occupied:textObstacles,dim:true,step:$0.offset) }',drawing)   # every multi-step guide builds up
        self.assertIn('marks:marks,avoid:calloutAvoid,fade:false)',drawing)   # a streamed caption's card stays off the earlier steps too
        for wiring in ('callout.onClose = { [weak self] in self?.clear() }','callout.onNext = { [weak self] in self?.next() }',
                       'callout.onBack = { [weak self] in self?.back() }'):
            self.assertIn(wiring,drawing)
        self.assertIn('guard Date() >= ready, waiting, hit?.contains(point) == true',drawing)
        self.assertIn('drawing.waiting, drawing.request?.guide == String(cue[0]), Int(cue[1]) ?? 0 > drawing.index { return }',source)   # read-aloud holds at a waiting step
        self.assertIn('drawing.waited = { [weak self] in self?.speakNext() }',source)
        self.assertIn('deadline = r.teaching ? .distantFuture',drawing)
        self.assertIn('else if !r.teaching { clear() }',drawing)
        self.assertIn('if !mathOnly, !driven, let caption = step.say, !caption.isEmpty, speechEnabled()',drawing)
        self.assertIn('shown = active && (!r.teaching || calloutPanel?.isVisible == true)',drawing)
        tick = drawing.split('func tick()',1)[1]
        self.assertIn('!manual, !driven, autoSteps(), index+1 < r.steps.count, voice?.isRunning != true',tick)   # Next / Back owns the guide; never over a sentence
        self.assertIn('Self.readingTime(cardText(step.say,step.shapes))',tick)   # silent steps stay for their reading time
        self.assertNotIn('status?(words)',drawing)   # step text lives beside its marks, never in the ask box
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        self.assertIn('drawing.autoSteps = { [weak self] in Prefs.str("guideSteps") != "next" && self?.voice == nil }',app)   # a capped read-aloud: its queued steps still come with their sentences
        self.assertIn('if let card = drawing.calloutLayout?.card { m = m.union(card) }',app)   # the box's line ends before the step card
        self.assertIn('(guided ? finish : result)',app)
        self.assertIn('deliver(guided ? finish : result, aloud: !guided)',app)   # a follow-up answer beside an old drawing still speaks
        self.assertIn('guard !marks.isNull else { clear(); return }',drawing)
        self.assertIn('guard display.intersects(global) else { return }',source)
        self.assertNotIn('drawing.advance()',app)   # a spoken or typed "next" takes over like the Next button
        self.assertIn('"guideSteps": "auto"',source)
        self.assertIn('"guideSteps"', source[source.index('static let retiredKeys'):])   # steps advance by themselves; no Settings row

    def test_user_mark_reaches_the_ask_and_has_bounded_fallback(self):
        with tempfile.NamedTemporaryFile(prefix='atticus-point-',suffix='.jpg') as image:
            value = {'bounds':[10,20,40,50], 'path':[[12,22],[20,30]], 'image':image.name,
                     'element':'Fixture AXButton: Continue'}
            context, shots = atticus.point_context(value)
            self.assertIn('path',context)
            self.assertIn('Fixture AXButton',context)
            self.assertEqual(shots[0][0],os.path.realpath(image.name))
        for bad in ({}, {'bounds':[0,0,1,1],'path':[],'element':'x'},
                    {'bounds':[0,0,-1,1],'path':[[0,0]],'element':'x'},
                    {'bounds':[0,0,1,1],'path':[[float('nan'),0]],'element':'x'}):
            with self.subTest(bad=bad):
                self.assertEqual(atticus.point_context(bad),('',[]))
        app = (ROOT/'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        self.assertIn('if let point { request["point"] = point }',app)
        self.assertIn('if drawing.hasInput { drawing.clearInput(); return }',app)
        self.assertIn('if !dictate && !drawing.hasInput { drawing.clear() }',app)
        self.assertNotIn('if drawing.active { drawing.clear() }',app.split('func startPointing()',1)[1].split('func finishPointing()',1)[0])   # pointing keeps a guide up

    def test_point_controls_reach_the_app(self):
        app = (ROOT/'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        for wiring in ('drawing.inputMode ? finishPointing() : startPointing()', 'drawing.inputAway = { [weak self] in self?.finishPointing() }',
                       'if b["pointClear"] != nil { if drawing.hasInput { drawing.clearInput() } else { clearPointContext() } }', 'Prefs.set("pointCoached", true)',
                       'drawing.picked = { [weak self] r, words in self?.finishPoint([CGPoint(x:r.minX,y:r.minY),CGPoint(x:r.maxX,y:r.maxY)],mark:words) }',
                       '!Prefs.bool("pointCoached") { js("pointCoach") }'):
            self.assertIn(wiring,app)
        self.assertNotIn('pointDone',app)
        begin = (ROOT/'Atticus.swift').read_text().split('func beginInput(',1)[1].split('func startInput(',1)[0]
        self.assertIn('panel.level = NSWindow.Level(rawValue:NSWindow.Level.statusBar.rawValue - 1)',begin)   # Atticus's .statusBar panels stay above it, even after a click raises it
        finish = app.split('func finishPoint(',1)[1].split('func startPointing()',1)[0]
        self.assertLess(finish.index('removeItem(atPath:old)'),finish.index('pointContext = context'),'a redrawn mark must delete the last crop')
        self.assertNotIn('thumb',finish.split('pointContext = context',1)[0].split('var context',1)[1],'the thumbnail is for the box, not the model request')
        ui = (ROOT/'ui'/'ui.html').read_text()
        self.assertIn('#comp.pick #model, #comp.pick #point, #comp.pick #mic { opacity: 0;',ui)   # the open Model row never shows the button through
        self.assertIn('Click, circle or scribble on anything, then ask',ui)
        bar = ui.split('<div id="pointbar"',1)[1].split('</div>',1)[0]
        self.assertNotIn('Done',bar); self.assertNotIn('Cancel',bar); self.assertNotIn('pointDone',ui)   # mark, then ask: nothing to confirm
        coach = ui.split('const coachShow',1)[1].split('};',1)[0]
        for words in ('circle, click or scribble on anything','type or say your question'):
            self.assertIn(words,coach)   # the first-open tip teaches it, so setup has no page for it
        self.assertNotIn('Draw on screen',ui)   # that name belongs to Atticus's own drawings
        for page in ('README.md','ui/settings.html'):
            self.assertIn('Point at your screen',(ROOT/page).read_text(),page)


@unittest.skipUnless(shutil.which('node'),'Node runs the box state check')
class PointBoxTests(unittest.TestCase):
    def test_point_states_with_fake_page(self):
        page = (ROOT/'ui'/'ui.html').read_text()
        setup = page[page.index('  // Point at your screen. The app owns'):page.index("  $('mic').onclick")]
        methods = page[page.index('    point(value) {'):page.index('    finished() {')]
        script = r'''
const el = (more = {}) => ({ dataset: {}, hidden: false, innerHTML: '', textContent: '', attrs: {}, src: '',
  classList: { s: new Set(), toggle(c, on) { on ? this.s.add(c) : this.s.delete(c); }, contains(c) { return this.s.has(c); } },
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; }, removeAttribute(k) { delete this.attrs[k]; if (k === 'src') this.src = ''; }, ...more });
const parts = { '.chip i': el(), '.rm': el(), '.gotit': el(), '.hint': el(), img: el({ hidden: true }) };
const els = { point: el({ innerHTML: '<svg></svg>' }), pointbar: el({ querySelector: s => parts[s] }), comp: el(), status: el() };
const $ = id => els[id], messages = [], post = m => messages.push(m), fit = () => {}, comps = [];
const status = s => { els.status.textContent = s; };
let working = false;
const comp = (on, focus) => { comps.push([on, !!focus]); els.comp.classList.toggle('open', on); if (on) coachShow(); };
''' + setup + 'const ui = {\n' + methods + r'''};
const fail = m => { console.error(m); process.exit(1); }, img = parts.img;
if (parts['.chip i'].innerHTML !== '<svg></svg>') fail('the chip has no pointer glyph for marks without a picture');
ui.pointCoach(); if (bar.dataset.s) fail('coach mark showed with the button hidden');
comp(true); if (bar.dataset.s !== 'coach' || !parts['.hint'].innerHTML.includes('Point at your screen')) fail('coach mark missing');
parts['.gotit'].onclick(); if (bar.dataset.s || messages.filter(m => m.pointCoached).length !== 1) fail('Got it did not end the coach mark');
comp(true); if (bar.dataset.s) fail('coach mark came back');
ui.point({ active: true, marked: false });
if (bar.dataset.s !== 'on' || parts['.hint'].textContent !== 'Click, circle or scribble on anything, then ask' || bar.classList.contains('has')) fail('pointing hint missing');
if (els.status.textContent !== 'Pointing…' || els.point.getAttribute('aria-pressed') !== 'true' || !els.point.classList.contains('active') || comps.at(-1).join() !== 'true,true') fail('pointing is not unmistakable: ' + els.status.textContent);
ui.point({ active: true, marked: true, thumb: 'data:image/jpeg;base64,AA' });
if (!bar.classList.contains('has') || img.hidden || img.src !== 'data:image/jpeg;base64,AA' || parts['.hint'].textContent) fail('a mark did not show its thumbnail');
if (markShot() !== 'data:image/jpeg;base64,AA') fail('the next ask would not carry the marked crop');
ui.point({ active: false, marked: true });
if (bar.dataset.s !== 'marked' || img.src !== 'data:image/jpeg;base64,AA' || els.status.textContent !== 'Marked' || els.point.getAttribute('aria-pressed') !== 'false') fail('leaving point mode lost the chip');
parts['.rm'].onclick();
if (messages.filter(m => m.pointClear).length !== 1) fail('the chip does not reach the app');
ui.point(false);
if (bar.dataset.s || !img.hidden || img.src || els.status.textContent !== '' || els.point.classList.contains('marked')) fail('clearing left the chip or status');
if (markShot()) fail('a cleared mark would still go with the next ask');
status('Thinking…'); ui.point(false); if (els.status.textContent !== 'Thinking…') fail('clearing a mark wiped another status');
ui.point({ active: false, marked: true, thumb: '' }); if (!img.hidden || markShot()) fail('an empty thumbnail showed a broken image');
working = true; const before = messages.length; els.point.onclick();
if (messages.slice(before).some(m => m.point) || els.status.textContent !== 'Finish or stop the current answer first') fail('pointing during an answer gave no reason');
'''
        result = subprocess.run(['node','--input-type=module'],input=script,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        listen = page[page.index('    listen(mode) {'):page.index('    level(v) {')]
        self.assertIn("!document.body.classList.contains('dictate') && markShot()",listen)   # the sent bubble shows the crop; dictation never does
        run = (ROOT/'Atticus.swift').read_text().split('    func run(_ t: String',1)[1]
        self.assertLess(run.index('pointContext = nil'),run.index('drawing.clearInput()'))   # sending takes the mark off the screen but keeps its crop for the worker


HARNESS = r'''
import Cocoa
func applySharing(_ window: NSWindow) { window.sharingType = .readOnly }
__DRAWING__
let app = NSApplication.shared; app.setActivationPolicy(.regular)
let window = NSWindow(contentRect:CGRect(x:120,y:100,width:850,height:560),styleMask:[.titled,.closable],backing:.buffered,defer:false)
window.title = "Atticus teaching fixture"; window.isReleasedWhenClosed = false; window.animationBehavior = .none; window.appearance = NSAppearance(named:.darkAqua)
window.backgroundColor = NSColor(calibratedWhite:0.12,alpha:1)
let title = NSTextField(labelWithString:"Learn by doing"); title.textColor = .white; title.font = .systemFont(ofSize:26,weight:.semibold); title.frame = CGRect(x:40,y:475,width:740,height:40); window.contentView!.addSubview(title)
let body = NSTextField(labelWithString:"A² + B² = C²"); body.textColor = .white; body.font = .systemFont(ofSize:32,weight:.medium); body.frame = CGRect(x:55,y:300,width:500,height:55); window.contentView!.addSubview(body)
let button = NSButton(checkboxWithTitle:"Try this control",target:nil,action:nil); button.frame = CGRect(x:400,y:185,width:200,height:38); window.contentView!.addSubview(button)
window.makeKeyAndOrderFront(nil); app.activate()
func pump(_ seconds: Double) { RunLoop.current.run(until:Date().addingTimeInterval(seconds)) }
pump(0.3)
let keyBefore = app.keyWindow
let frontBefore = NSWorkspace.shared.frontmostApplication?.processIdentifier
let info = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as! [[String:Any]])[0]
let frame = CGRect(dictionaryRepresentation:info[kCGWindowBounds as String] as! CFDictionary)!
let target: [String:Any] = ["pid":ProcessInfo.processInfo.processIdentifier,"windowID":String(window.windowNumber),"windowFrame":[frame.minX,frame.minY,frame.width,frame.height]]
let x=frame.minX, y=frame.minY
let steps: [[String:Any]] = [
 ["id":"geometry","wait":true,"hit":[x+50,y+150,230,220],"shapes":[
  ["kind":"path","points":[[x+70,y+330],[x+270,y+330],[x+270,y+170],[x+70,y+330]],"color":"blue"],
  ["kind":"rect","rect":[x+70,y+330,200,200],"color":"green"],
  ["kind":"label","at":[x+100,y+330],"text":"Leg A"],
  ["kind":"label","at":[x+270,y+200],"text":"Leg B"],
  ["kind":"pointer","at":[x+190,y+230]]]],
 ["id":"control","wait":true,"hit":[x+400,y+350,200,38],"shapes":[
  ["kind":"circle","rect":[x+390,y+345,210,50],"color":"yellow"],
  ["kind":"arrow","points":[[x+640,y+280],[x+495,y+345]]],
  ["kind":"label","at":[x+495,y+345],"text":"Try this control"],
  ["kind":"pointer","at":[x+410,y+370]]]],
 ["id":"finish","shapes":[["kind":"line","points":[[x+60,y+120],[x+650,y+120]],"color":"blue"],
  ["kind":"label","at":[x+450,y+210],"text":"You did it"],
  ["kind":"pointer","at":[x+450,y+240]]]]]
func data(_ steps: [[String:Any]], teaching: Bool = false) -> Data { try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":teaching,"target":target,"state":"fixture"]) }
func refused(_ d: Data) -> String {   // which check turned a guide away
 guard let r = try? JSONDecoder().decode(DrawingRequest.self,from:d) else { return "did not decode" }
 let w = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as? [[String:Any]])?.first?[kCGWindowBounds as String]
 return "valid \(ScreenDrawing.valid(r)) on displays \(ScreenDrawing.onDisplays(r)) window current \(ScreenDrawing.current(r.target)) (now \(String(describing: w)), sent \(r.target.windowFrame)) screens \(NSScreen.screens.map(\.frame))"
}
let drawing = ScreenDrawing()
var marked: [CGPoint] = []
drawing.beginInput { marked = $0 }
precondition(drawing.inputPanels.count == NSScreen.screens.count && drawing.inputPanels.allSatisfy { !$0.ignoresMouseEvents && !$0.canBecomeKey && !$0.canBecomeMain })
precondition(app.keyWindow === keyBefore && NSWorkspace.shared.frontmostApplication?.processIdentifier == frontBefore,
             "Point input changed the focused app or key window")
precondition(drawing.inputPanels.allSatisfy { ($0.contentView as? DrawingView)?.pointing == true && $0.acceptsMouseMovedEvents },"Pointing has no crosshair cursor")
drawing.startInput(CGPoint(x:x+100,y:y+200)); drawing.moveInput(CGPoint(x:x+140,y:y+240)); drawing.endInput(CGPoint(x:x+140,y:y+240))
precondition(marked.count == 2 && drawing.inputMode && drawing.inputPanels.allSatisfy { !$0.ignoresMouseEvents },"A stroke ended pointing at once")
precondition(drawing.inputPanels.allSatisfy { $0.level.rawValue < NSWindow.Level.statusBar.rawValue },"Pointing can cover Atticus's own panels")
drawing.startInput(CGPoint(x:x+300,y:y+300)); drawing.endInput(CGPoint(x:x+300,y:y+300))
precondition(marked == [CGPoint(x:x+300,y:y+300)] && drawing.inputPath.count == 1,"A new stroke did not replace the last mark")
drawing.inputAway = { drawing.finishInput() }
drawing.hoverInput(CGPoint(x:x+340,y:y+340)); precondition(drawing.inputMode,"Moving near the mark ended pointing")
drawing.hoverInput(CGPoint(x:x+500,y:y+300))
precondition(!drawing.inputMode && drawing.hasInput && drawing.inputPanels.allSatisfy { $0.ignoresMouseEvents && ($0.contentView as? DrawingView)?.pointing == false },"Moving off the mark did not keep it and hand clicks back")
drawing.startInput(CGPoint(x:x+10,y:y+10)); precondition(drawing.inputPath.count == 1,"A click after pointing changed the mark")
drawing.clear(); precondition(!drawing.hasInput && drawing.inputPanels.isEmpty,"Point input did not clear")
drawing.beginInput { _ in }; drawing.hoverInput(nil); precondition(drawing.inputMode,"Leaving before any mark ended pointing")
drawing.inputAway = nil
var cleared = 0; drawing.inputCleared = { cleared += 1 }
drawing.finishInput()
precondition(!drawing.hasInput && drawing.inputPanels.isEmpty && cleared == 1,"Turning pointing off with no mark did not cancel")
drawing.inputCleared = nil
precondition(drawing.receive(data(steps)),refused(data(steps)))
precondition(drawing.panels.count == NSScreen.screens.count)
drawing.beginInput { _ in }; precondition(drawing.active && drawing.panels.count == NSScreen.screens.count,"Pointing cleared the guide")
drawing.clearInput(); precondition(drawing.active && drawing.inputPanels.isEmpty,"Clearing a mark took the guide")
var picked = ""; drawing.picked = { _, words in picked = words }
let markView = drawing.panels.compactMap { $0.contentView as? DrawingView }.first { $0.hits.contains { $0.shape == 2 } }!
let legA = markView.hits.first { $0.shape == 2 }!.area.boundingBoxOfPath.offsetBy(dx:markView.origin.x,dy:markView.origin.y)
drawing.pick(CGPoint(x:legA.midX,y:legA.midY))
precondition(picked.hasPrefix("label \"Leg A\" in step 1 of 3") && drawing.selected?.shape == 2 && drawing.manual,"Clicking a mark did not select it: \(picked)")
precondition(markView.layer!.sublayers!.contains { $0.name == "pick" },"The selected mark has no highlight")
drawing.deselect(); precondition(drawing.selected == nil && !markView.layer!.sublayers!.contains { $0.name == "pick" })
drawing.manual = false; drawing.picked = nil
precondition(app.keyWindow === keyBefore && NSWorkspace.shared.frontmostApplication?.processIdentifier == frontBefore,
             "Drawing changed the focused app or key window")
for panel in drawing.panels {
 precondition(!panel.canBecomeKey && !panel.canBecomeMain && panel.ignoresMouseEvents && !panel.isKeyWindow && !panel.isMainWindow)
 precondition(panel.collectionBehavior.contains(.canJoinAllSpaces) && panel.collectionBehavior.contains(.fullScreenAuxiliary))
 precondition(panel.styleMask.contains(.nonactivatingPanel))
}
func shot(_ name: String) {
 drawing.deadline = .distantFuture // screenshot encoding is not part of the timeout behavior under test
 pump(0.4)
 let file = NSTemporaryDirectory()+name+".png", p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); p.arguments = ["-x",file]
 try! p.run(); p.waitUntilExit()
 if let bytes = try? Data(contentsOf:URL(fileURLWithPath:file)), !bytes.isEmpty { print("DRAW_SCREENSHOT \(name) \(bytes.base64EncodedString())") }
 else { preconditionFailure("Fixture screenshot failed") }
}
shot("01-geometry")
precondition(drawing.active,"Guide cleared before click")
drawing.ready = .distantPast
drawing.clicked(CGPoint(x:x+800,y:y+500)); precondition(drawing.index == 0,"Outside click advanced step")
drawing.clicked(CGPoint(x:x+100,y:y+200)); precondition(drawing.index == 1,"Target click did not advance")
shot("02-control")
drawing.advance(); precondition(drawing.index == 2)
shot("03-finish")
func cardClear() -> Bool {
 guard let panel = drawing.calloutPanel else { return false }
 let top = NSScreen.screens[0].frame.maxY, f = panel.frame
 let card = CGRect(x:f.minX,y:top-f.maxY,width:f.width,height:f.height)
 return NSScreen.screens.contains { $0.visibleFrame.contains(f) } && !drawing.panels.flatMap { ($0.contentView as? DrawingView)?.hitBounds ?? [] }.contains { $0.intersects(card) }
}
let panels = drawing.panels
var cleanups = 0; drawing.cleanup = { cleanups += 1 }
drawing.clear(); precondition(cleanups == 1,"AX session was not restored on clear"); precondition(!drawing.active && drawing.voice == nil && drawing.timer == nil && drawing.monitors.isEmpty && panels.allSatisfy { !$0.isVisible })
let lesson: [[String:Any]] = [["say":"Draw the square.","shapes":[["kind":"rect","rect":[x+60,y+150,200,200]]]],
                              ["say":"Label its side.","shapes":[["kind":"label","at":[x+160,y+250],"text":"x"]]]]
precondition(drawing.receive(data(lesson,teaching:true)) && drawing.calloutPanel?.isVisible == true,"Whiteboard step had no callout")
let lessonFrame = drawing.calloutPanel!.frame
precondition(!drawing.calloutPanel!.frame.intersects(CGRect(x:x+60,y:NSScreen.screens[0].frame.maxY-(y+350),width:200,height:200)),"Callout covered its mark")
drawing.tick(); precondition(drawing.index == 0,"Silent step moved on before its reading time")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 1 && !drawing.manual,"Silent step did not move on after its reading time")
let lessonViews = drawing.panels.compactMap { $0.contentView as? DrawingView }
precondition(lessonViews.flatMap { $0.hits }.contains { $0.step == 0 } && lessonViews.flatMap { $0.hits }.contains { $0.step == 1 },"The earlier step's marks vanished")
precondition(lessonViews.flatMap { $0.layer?.sublayers ?? [] }.contains { $0.opacity == 0.5 },"The earlier step's marks are not dimmed")
precondition(cardClear(),"The auto step covered the drawing")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 1 && drawing.active,"The last step did not stay")
drawing.back(); precondition(drawing.index == 0 && drawing.manual,"Back did not return to the last step")
precondition(drawing.panels.compactMap { $0.contentView as? DrawingView }.flatMap { $0.hits }.allSatisfy { $0.step == 0 },"Back left the later step's marks")
precondition(drawing.calloutPanel?.frame == lessonFrame,"Back moved the step panel")
drawing.showStep(forward:false,mathOnly:true)
precondition(drawing.calloutPanel?.frame == lessonFrame,"Math reflow moved the step panel")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 0,"Auto steps fought the user's Back")
drawing.next(); precondition(drawing.index == 1); drawing.next(); precondition(!drawing.active,"Done on the last step did not clear")
func streamed(_ steps: [[String:Any]], _ guide: String) -> Data { try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":true,"target":target,"state":"fixture","guide":guide]) }
drawing.driven = true
precondition(drawing.update(streamed(Array(lesson[..<1]),"g1")) && drawing.index == 0,"A streamed guide's first step did not show")
func inked() -> [ObjectIdentifier] { drawing.panels.flatMap { $0.contentView?.layer?.sublayers ?? [] }.map(ObjectIdentifier.init) }
let firstInk = inked()
precondition(drawing.update(streamed(lesson,"g1")) && drawing.index == 0 && drawing.request?.steps.count == 2,"A streamed step moved the shown one")
precondition(!firstInk.isEmpty && inked() == firstInk && drawing.calloutPanel?.isVisible == true,"A streamed step redrew the shown marks, cutting their ink short")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 0 && drawing.voice == nil,"A spoken guide stepped or talked by itself")
drawing.reveal(1); precondition(drawing.index == 1,"The voice did not bring in the next step")
var recaptioned = lesson; recaptioned[1]["say"] = String(repeating:"Label its side and read it back. ",count:6)
precondition(drawing.update(streamed(recaptioned,"g1")) && drawing.index == 1 && cardClear(),"A streamed caption moved the card onto an earlier step")
precondition(drawing.update(streamed(Array(lesson[..<1]),"g2")) && drawing.index == 0 && drawing.request?.steps.count == 1,"Another guide did not start over")
drawing.driven = false; drawing.clear()
precondition(!drawing.update(streamed(lesson,"g2")) && !drawing.active,"A late caption update reopened a dismissed guide")
precondition(drawing.update(streamed(lesson,"g3")),"Dismissing a guide blocked a new one")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 1,"Shush did not return a streamed guide to its reading time")
drawing.back(); drawing.next(); precondition(drawing.index == 1,"Manual navigation lost a streamed step")
drawing.clear()
let clickDir = NSTemporaryDirectory()+UUID().uuidString; try! FileManager.default.createDirectory(atPath:clickDir,withIntermediateDirectories:true)
func inline(_ steps: [[String:Any]], _ guide: String) -> Data { try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":true,"target":target,"state":"fixture","guide":guide,"cancelFile":clickDir+"/guide-cancelled"]) }
let doThis: [String:Any] = ["say":"Click this control.","wait":true,"hit":[x+400,y+350,200,38],"shapes":[["kind":"rect","rect":[x+400,y+350,200,38]]]]
let explain: [String:Any] = ["say":"This square shows the result.","shapes":[["kind":"circle","rect":[x+60,y+150,80,80]]]]
let thenThis: [String:Any] = ["say":"Now click here.","wait":true,"hit":[x+300,y+160,50,50],"shapes":[["kind":"circle","rect":[x+300,y+160,50,50]]]]
precondition(drawing.update(inline([doThis],"click")) && drawing.waiting,"An inline click step was refused or did not wait")
drawing.ready = .distantPast; drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 0 && drawing.waiting,"A click step moved on by its reading time")
drawing.clicked(CGPoint(x:x+800,y:y+500)); precondition(drawing.waiting,"A click outside the mark counted")
drawing.clicked(CGPoint(x:x+450,y:y+360))
precondition(drawing.active && drawing.index == 0 && !drawing.waiting && !drawing.manual,"A click in the last streamed step's mark closed it or took over narration")
precondition(FileManager.default.fileExists(atPath:ScreenDrawing.clickFile(clickDir+"/guide-cancelled")),"The click did not reach a walkthrough's watch")
precondition(drawing.update(inline([doThis,explain,thenThis],"click")) && drawing.index == 0,"A streamed step moved the shown one")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 1,"The step after a done click did not come in")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 2 && drawing.waiting,"An explanation step did not follow its reading time")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 2 && drawing.waiting,"A click step moved on by its reading time")
drawing.ready = .distantPast; drawing.clicked(CGPoint(x:x+325,y:y+185)); precondition(drawing.active && !drawing.waiting,"The last click step closed the guide")
drawing.clear()
precondition(drawing.update(inline([doThis,explain,thenThis],"mixed")) && drawing.waiting)
var held = 0; drawing.waited = { held += 1 }
drawing.ready = .distantPast; drawing.clicked(CGPoint(x:x+800,y:y+500)); precondition(drawing.index == 0 && held == 0,"A click outside the mark advanced")
drawing.clicked(CGPoint(x:x+450,y:y+360)); precondition(drawing.index == 1 && held == 1 && !drawing.manual,"A click in the mark did not show the next step and resume narration")
drawing.waited = nil; drawing.clear()
precondition(drawing.update(inline([explain,explain],"explain")) && !drawing.waiting)
drawing.ready = .distantPast; drawing.clicked(CGPoint(x:x+100,y:y+190)); precondition(drawing.index == 0,"An explanation advanced from a screen click")
drawing.shownAt = .distantPast; drawing.tick(); precondition(drawing.index == 1,"An explain-only guide stopped stepping by itself")
drawing.clear(); try? FileManager.default.removeItem(atPath:clickDir)
let growing: [[String:Any]] = [["say":"Short.","shapes":[["kind":"circle","rect":[x+300,y+160,50,50]]]]]
precondition(drawing.update(streamed(growing,"grow")))
let initialCard = drawing.calloutPanel!.frame
var expanded = growing; expanded[0]["say"] = String(repeating:"Read the table and compare the entries. ",count:20)
precondition(drawing.update(streamed(expanded,"grow")))
precondition(drawing.calloutPanel!.frame.height > initialCard.height && drawing.textPageCount <= 2,"Streamed caption stayed in the first tiny card")
precondition(NSScreen.screens.contains { $0.visibleFrame.contains(drawing.calloutPanel!.frame) },"Grown card escaped visibleFrame")
drawing.clear()
let varying: [[String:Any]] = [["say":"First.","shapes":[["kind":"circle","rect":[x+300,y+160,50,50]]]],
    ["say":String(repeating:"Read this next. ",count:40),"shapes":[["kind":"circle","rect":[x+500,y+300,50,50]]]]]
precondition(drawing.receive(data(varying,teaching:true)),"Varying captions did not fit")
let fixed = drawing.calloutPanel!.frame
for _ in 0..<3 {
    drawing.next(); precondition(drawing.index == 1 && cardClear(),"A larger caption covered its marks")
    drawing.back(); precondition(drawing.index == 0 && drawing.calloutPanel?.frame == fixed,"Back from a larger caption moved the panel")
}
drawing.clear()
let anchored: [[String:Any]] = [["target":"Exact control","wait":true,"shapes":[["kind":"rect"],["kind":"pointer"],["kind":"label","text":"Here"]]],steps[2]]
let nativeTarget = try! JSONDecoder().decode(DrawingWindow.self,from:JSONSerialization.data(withJSONObject:target))
let anchor = CGRect(x:x+400,y:y+350,width:200,height:38)
var value = 0
drawing.resolve = { _,_ in (anchor,AXUIElementCreateApplication(getpid()),nativeTarget) }
drawing.readValue = { _ in NSNumber(value:value) }
precondition(drawing.receive(data(anchored)))
precondition(drawing.hit == anchor,"AX frame was not used")
drawing.ready = .distantPast; value = 1; drawing.tick(); precondition(drawing.index == 1,"Value change did not advance")
let motion = DrawingView(frame:CGRect(x:0,y:0,width:100,height:100))
let shape = DrawingShape(kind:"line",points:[[1,2],[30,40]])
motion.render([shape],animate:false,previous:nil); precondition(motion.layer!.sublayers!.allSatisfy { $0.animationKeys() == nil },"Reduced motion animated")
motion.render([shape],animate:true,previous:nil); precondition(motion.layer!.sublayers!.first!.animation(forKey:"draw") != nil)
let speech = Process(); speech.executableURL = URL(fileURLWithPath:"/bin/sleep"); speech.arguments = ["30"];try! speech.run(); drawing.voice=speech
drawing.clear(); speech.waitUntilExit(); precondition(!speech.isRunning && drawing.voice == nil,"Cancel left voice running")
precondition(drawing.receive(data(steps)))
drawing.deadline = .distantPast; drawing.tick(); precondition(!drawing.active,"Timeout did not clear")
precondition(drawing.receive(data(steps)))
window.setFrameOrigin(CGPoint(x:window.frame.minX+30,y:window.frame.minY)); pump(0.2); drawing.tick(); precondition(!drawing.active,"Window movement did not clear")
var bad = target; bad["windowFrame"] = [0,0,-1,1]
let invalid = try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":false,"target":bad,"state":"fixture"])
precondition(!drawing.receive(invalid),"Native accepted invalid frame")
precondition(!drawing.receive(data(steps)),"Stale screenshot geometry was shown")
window.setFrameOrigin(CGPoint(x:window.frame.minX-30,y:window.frame.minY)); pump(0.1)
precondition(drawing.receive(data(steps)))
window.orderOut(nil); pump(0.1); drawing.tick(); precondition(!drawing.active,"Closed window did not clear")
let outside = [["shapes":[["kind":"pointer","at":[99999,99999]]]]]
precondition(!drawing.receive(data(outside)),"Native accepted off-display coordinates")
let mixed = [["shapes":[["kind":"line","points":[[1,2],[3,4]],"rect":[1]]]]]
precondition(!drawing.receive(data(mixed)),"Native accepted coordinates for another shape kind")
print("Native drawings: click-through, never key/main, all displays/spaces, target click, next, clear, timeout, moved window, validation passed")
window.orderOut(nil)
'''


@unittest.skipUnless(sys.platform == 'darwin','macOS native drawing fixture')
class NativeDrawingTests(unittest.TestCase):
    def test_product_typechecks(self):
        result = subprocess.run(['swiftc','-typecheck',str(ROOT/'Atticus.swift')],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_native_drawings_and_fixture_screenshots(self):
        from tests.test_guidecard import dismiss_vm_consent
        dismiss_vm_consent(self)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = (ROOT/'Atticus.swift').read_text()
            drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
            (root/'main.swift').write_text(HARNESS.replace('__DRAWING__',drawing))
            result = subprocess.run(['swiftc',str(root/'main.swift'),'-o',str(root/'fixture')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([str(root/'fixture')],capture_output=True,text=True,timeout=25,
                                    env={**os.environ,'ATTICUS_DIR':folder})
            self.assertEqual(result.returncode,0,result.stdout[-1500:]+result.stderr[-2000:])
            # VM artifacts travel through stdout because the runner shuts the guest down immediately.
            self.assertEqual(result.stdout.count('DRAW_SCREENSHOT '),3)
            print(result.stdout,flush=True)


@unittest.skipUnless(sys.platform == 'darwin','macOS Swift drawing anchor check')
class DrawingAnchorTests(unittest.TestCase):
    def test_ids_keep_identity_across_expected_value_changes(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        method = source[source.index('    static func drawAnchor('):source.index('    static func point(_ text:')]
        harness = r'''import Cocoa
typealias AXUIElement = Int
struct DrawingWindow { let pid:Int32,windowID:String,windowFrame:[Double] }
struct MiniScreen { static func bounds(_ info:[String:Any])->CGRect? { CGRect(x:10,y:20,width:300,height:200) } }
func CGWindowListCopyWindowInfo(_ option: CGWindowListOption,_ id:UInt32)->CFArray? { [["fixture":true]] as CFArray }
enum Hands {
 struct Failure: Error { let message:String;init(_ message:String){self.message=message} }
 struct Node:Codable { var id:Int,role:String,label:String,path:[Int],value:String }
 struct Map:Codable { var pid:Int32,windowID:String,windowFrame:[Double],nodes:[Node] }
 static var fresh = Map(pid:1,windowID:"5",windowFrame:[10,20,300,200],nodes:[Node(id:9,role:"AXButton",label:"Control",path:[2,3],value:"on")])
 static func app(_ pid:String)throws->Int {1}
 static func capture(_ app:Int)throws->Map {fresh}
 static func at(_ path:[Int],_ app:Int)throws->AXUIElement { precondition(path == [2,3]);return 42 }
 static func visibleFrame(_ e:AXUIElement)->CGRect { CGRect(x:40,y:50,width:60,height:20) }
 static func array(_ r:CGRect)->[Double] {[r.minX,r.minY,r.width,r.height]}
 static func resolve(_ label:String,map:Map,a:Int)throws->(Node,AXUIElement?) { throw Failure("ID resolution must preserve its original path") }
''' + method + r''' }
let file = NSTemporaryDirectory()+UUID().uuidString
var old=Hands.fresh;old.nodes[0].id=1;old.nodes[0].value="off"
try! JSONEncoder().encode(old).write(to:URL(fileURLWithPath:file));defer {try? FileManager.default.removeItem(atPath:file)}
let result = try! Hands.drawAnchor("1",state:file)
precondition(result.0 == CGRect(x:40,y:50,width:60,height:20) && result.1 == 42,"Value change lost target identity")
for mutation in 0..<3 {
 Hands.fresh=old
 if mutation == 0 { Hands.fresh.nodes[0].label="Different control" }
 else if mutation == 1 { Hands.fresh.nodes[0].path=[5] }
 else { Hands.fresh.windowFrame[0] += 30 }
 do { _ = try Hands.drawAnchor("1",state:file);preconditionFailure("Changed target was accepted") } catch {}
}
print("Stable AX anchor identity and stale-target rejection passed")
'''
        self.assertIn('Stable AX anchor',run_swift(self,harness))


GEOMETRY = r'''
import Cocoa
func applySharing(_ window: NSWindow) {}
__DRAWING__
let gap = ScreenDrawing.gap, t = CGRect(x:100,y:100,width:80,height:20)
func inEllipse(_ p: CGPoint, _ e: CGRect) -> Bool { let dx = (p.x-e.midX)/(e.width/2), dy = (p.y-e.midY)/(e.height/2); return dx*dx+dy*dy <= 1 }
let corners = [CGPoint(x:t.minX,y:t.minY),CGPoint(x:t.maxX,y:t.minY),CGPoint(x:t.minX,y:t.maxY),CGPoint(x:t.maxX,y:t.maxY)]
precondition(ScreenDrawing.ring(t,circle:false).insetBy(dx:1.5+gap,dy:1.5+gap) == t,"A box's stroke must sit outside its target")
precondition(corners.allSatisfy { inEllipse($0,ScreenDrawing.ring(t,circle:true).insetBy(dx:1.5,dy:1.5)) },"A circle's stroke cut through its target")
let tip = ScreenDrawing.arrowTip(from:CGPoint(x:300,y:110),to:CGPoint(x:140,y:110),avoiding:[t])
precondition(!t.insetBy(dx:-gap,dy:-gap).contains(tip) && tip.x > t.maxX && tip.x < t.maxX+gap+4,"An arrow head landed on its target: \(tip)")
precondition(ScreenDrawing.arrowTip(from:.zero,to:CGPoint(x:50,y:50),avoiding:[t]) == CGPoint(x:50,y:50),"An arrow to open space moved")
precondition(!t.contains(ScreenDrawing.beside(CGPoint(x:t.midX,y:t.midY),[t])) && ScreenDrawing.beside(CGPoint(x:5,y:5),[t]) == CGPoint(x:5,y:5))
let lead = ScreenDrawing.leader(from:CGRect(x:600,y:80,width:340,height:120),to:t)!
precondition(lead.0 == CGPoint(x:600,y:110) && !t.insetBy(dx:-gap,dy:-gap).contains(lead.1) && lead.1.x > t.maxX && lead.1.x < t.maxX+gap+4,"The leader line does not run from the box edge to just outside its target: \(lead)")
precondition(ScreenDrawing.leader(from:CGRect(x:190,y:90,width:340,height:120),to:t) == nil,"A target beside the box got a leader line")
let area = CGRect(x:0,y:0,width:1000,height:800), keep = [t.insetBy(dx:-gap,dy:-gap)], tag = CGSize(width:60,height:26)
let onTarget = ScreenDrawing.labelBox(tag,at:CGPoint(x:t.midX,y:t.midY),keepOff:keep,in:area)
precondition(!keep[0].intersects(onTarget) && area.contains(onTarget),"A label covered the thing it names")
precondition(ScreenDrawing.labelBox(tag,at:CGPoint(x:500,y:500),keepOff:keep,in:area).origin == CGPoint(x:512,y:470),"A free label moved")
precondition(area.contains(ScreenDrawing.labelBox(tag,at:CGPoint(x:995,y:2),keepOff:[],in:area)),"A label left the screen")
let square = CGRect(x:300,y:300,width:200,height:200), inside = ScreenDrawing.labelBox(tag,at:CGPoint(x:380,y:420),keepOff:[square],in:area)
precondition(!inside.intersects(square),"An area-model label covered its mark")
let edgeLabel = ScreenDrawing.labelBox(tag,at:CGPoint(x:490,y:420),keepOff:[square],in:area)
precondition(!edgeLabel.intersects(square) || square.insetBy(dx:2*gap,dy:2*gap).contains(edgeLabel),"A label crossed a mark's edge")

let view = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800)); view.origin = CGPoint(x:-200,y:50)
let g = CGRect(x:100,y:300,width:120,height:24)
let drawn = view.render([DrawingShape(kind:"circle",rect:[100,300,120,24]),DrawingShape(kind:"label",at:[160,312],text:"x² + 6x"),
                         DrawingShape(kind:"arrow",points:[[500,312],[160,312]],color:"blue")],animate:false,previous:nil)
precondition(drawn.contains(g),"Drawn bounds miss the ring")
let layers = view.layer!.sublayers!, global = { (r: CGRect) in r.offsetBy(dx:view.origin.x,dy:view.origin.y) }
for text in layers.compactMap({ $0 as? CATextLayer }) { precondition(!global(text.frame).intersects(g),"Label text sits on its target") }
let arrow = layers.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(global(arrow.path!.boundingBoxOfPath).minX > g.maxX,"Arrow head sits on its target")
let diagram = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
diagram.render([DrawingShape(kind:"circle",rect:[100,100,300,220],color:"green",fill:true),
                DrawingShape(kind:"label",at:[250,210],text:"Cell membrane",color:"blue",size:"l")],animate:false,previous:nil)
let part = diagram.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemGreen.cgColor }!
precondition(part.path!.boundingBoxOfPath == CGRect(x:100,y:100,width:300,height:220) && (part.fillColor?.alpha ?? 0) > 0,
             "A filled ellipse is not an exact, visible diagram part")
func outlines(_ v: DrawingView) -> [CGRect] { v.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.filter { $0.strokeColor == NSColor.systemBlue.cgColor }.map { $0.path!.boundingBoxOfPath } }
let legs = DrawingShape(kind:"path",points:[[190,100],[190,190],[310,190]]), onLeg = DrawingShape(kind:"rect",rect:[100,100,90,90],color:"blue")
let figure = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
figure.render([onLeg],animate:false,previous:nil,parts:[legs,onLeg])
precondition(outlines(figure) == [CGRect(x:100,y:100,width:90,height:90)],"A figure's square is not at its exact bounds on the earlier leg: \(outlines(figure))")
let onBase = DrawingView(frame:figure.frame)
onBase.render([legs,DrawingShape(kind:"rect",rect:[190,190,120,120],color:"blue")],animate:false,previous:nil)
precondition(outlines(onBase) == [CGRect(x:190,y:190,width:120,height:120)],"A square sharing the base's edge grew off it: \(outlines(onBase))")
let wheel = DrawingView(frame:figure.frame)
wheel.render([DrawingShape(kind:"circle",rect:[400,400,100,100],color:"blue"),DrawingShape(kind:"line",points:[[450,450],[500,450]])],animate:false,previous:nil)
precondition(outlines(wheel) == [CGRect(x:400,y:400,width:100,height:100)],"A circle its radius reaches is not at its exact bounds: \(outlines(wheel))")
let control = DrawingView(frame:figure.frame), button = CGRect(x:400,y:400,width:120,height:30)
control.render([DrawingShape(kind:"rect",rect:[400,400,120,30],color:"blue"),DrawingShape(kind:"arrow",points:[[700,415],[520,415]],color:"red"),
                DrawingShape(kind:"label",at:[700,415],text:"Save")],animate:false,previous:nil,parts:[legs])
let around = ScreenDrawing.ring(button,circle:false), drawnBox = outlines(control)   // drawn by hand: about a point off the ring, never onto the control
precondition(drawnBox.count == 1 && [drawnBox[0].minX-around.minX,drawnBox[0].minY-around.minY,drawnBox[0].maxX-around.maxX,drawnBox[0].maxY-around.maxY].allSatisfy { abs($0) < 4 }
             && drawnBox[0].insetBy(dx:4,dy:4).contains(button),"A ring around a control lost its clear gap: \(drawnBox)")
let twice = [DrawingView(frame:figure.frame), DrawingView(frame:figure.frame)]
twice.forEach { $0.render([DrawingShape(kind:"circle",rect:[400,400,120,30],color:"blue")],animate:false,previous:nil) }
let ringPaths = twice.map { $0.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!.path! }
precondition(ringPaths[0] == ringPaths[1],"The same mark came out a different shape")
let marker = DrawingView(frame:figure.frame)
marker.render([DrawingShape(kind:"rect",rect:[100,100,200,20],color:"yellow",fill:true)],animate:true,previous:nil)
let band = marker.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first!
precondition(band.strokeColor == nil && band.mask?.animation(forKey:"wipe") != nil && band.path!.boundingBoxOfPath == CGRect(x:100,y:98,width:200,height:24),
             "A highlight is not a highlighter band wiped on: \(band.path!.boundingBoxOfPath)")
let helper = DrawingView(frame:figure.frame)
helper.render([DrawingShape(kind:"line",points:[[10,200],[300,200]],color:"blue",dashed:true),DrawingShape(kind:"label",at:[300,200],text:"h",color:"blue")],animate:false,previous:nil)
let helperLine = helper.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(helperLine.lineDashPattern == [7,5] && helperLine.path!.boundingBoxOfPath.height == 0,"A dashed helper line is not dashed and straight")
precondition(helper.layer!.sublayers!.filter { $0 is CATextLayer }.allSatisfy { $0.zPosition > helperLine.zPosition },"A name is not above the ink")
precondition(diagram.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!.frame.height > 20,"A large diagram label stayed tiny")
let dim = DrawingView(frame:view.frame); dim.render([DrawingShape(kind:"line",points:[[1,2],[30,40]])],animate:false,previous:nil,dim:true)
precondition(dim.layer!.sublayers!.allSatisfy { $0.opacity == 0.5 },"Earlier whiteboard steps are not quieter")
func start(_ l: CAShapeLayer) -> CGPoint { var p: CGPoint?; l.path!.applyWithBlock { e in if p == nil, e.pointee.type == .moveToPoint { p = e.pointee.points[0] } }; return p! }
let coil = DrawingShape(kind:"rect",rect:[100,100,200,150],color:"green"), flow = DrawingView(frame:view.frame)
flow.render([DrawingShape(kind:"arrow",points:[[200,250],[200,450]],color:"blue"),DrawingShape(kind:"label",at:[200,250],text:"gas",color:"blue")],
            animate:false,previous:nil,parts:[coil],dim:true)
let flowArrow = flow.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
let flowName = flow.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!
precondition(abs(start(flowArrow).x-200) < 0.5 && abs(start(flowArrow).y-(250+gap+1.5)) < 1,"An arrow from an earlier part left its edge: \(start(flowArrow))")
precondition(flowName.frame.minX > 200 && flowName.frame.midY > 300 && flowName.frame.midY < 400 && flowName.opacity == 1 && flowArrow.opacity == 0.5,
             "A joining arrow's name is not readable beside its middle: \(flowName.frame)")
let bent = DrawingView(frame:view.frame)
bent.render([DrawingShape(kind:"path",points:[[200,250],[200,400],[500,400]],color:"blue"),DrawingShape(kind:"arrow",points:[[500,400],[500,300]],color:"blue"),
             DrawingShape(kind:"label",at:[200,250],text:"returns",color:"blue")],animate:false,previous:nil,parts:[coil])
let bentPath = bent.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
let bentName = bent.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!
precondition(abs(start(bentPath).y-(250+gap+1.5)) < 1 && bentName.frame.minX > 350 && bentName.frame.maxY < 400 && bentName.frame.midY > 340,
             "A bent arrow from a part left its edge, or its name is not on its longest run: \(start(bentPath)) \(bentName.frame)")
let pill = DrawingView(frame:view.frame)
pill.render([DrawingShape(kind:"arrow",points:[[600,500],[800,500]],color:"blue"),DrawingShape(kind:"label",at:[600,500],text:"here",color:"blue")],animate:false,previous:nil,parts:[coil])
let pillArrow = pill.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(abs(start(pillArrow).x-(pill.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!.frame.maxX+8)) < 1,"A callout arrow no longer starts at its name")
let boardFrame = CGRect(x:0,y:0,width:300,height:100), boardPad: CGFloat = 8
let boardLines = [
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"First"),rect:CGRect(x:8,y:10,width:100,height:20),step:0,shape:0),
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"Middle"),rect:CGRect(x:8,y:70,width:100,height:20),step:1,shape:0),
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"Later"),rect:CGRect(x:8,y:150,width:100,height:30),step:2,shape:0)]
let laterPage = ScreenDrawing.boardPage((boardFrame,boardPad,boardLines),through:2)!
precondition(laterPage.lines.contains { $0.step == 2 } && laterPage.lines.allSatisfy { $0.rect.minY >= boardPad && $0.rect.maxY <= boardFrame.maxY-boardPad },
             "Long whiteboard dropped or clipped the active step")
let earlierPage = ScreenDrawing.boardPage((boardFrame,boardPad,boardLines),through:0)!
precondition(earlierPage.lines.map(\.step) == [0],"Back could not page earlier whiteboard text into view")

let size = CGSize(width:240,height:120), marks = CGRect(x:100,y:100,width:200,height:50)
var (card, side) = ScreenDrawing.calloutFrame(size,marks:marks,avoid:[],in:area)
precondition(side == .minX && card.minX > marks.maxX && card.minX-marks.maxX < 24 && !card.intersects(marks),"Callout is not beside its marks")
let edge = CGRect(x:700,y:100,width:250,height:50)
(card, side) = ScreenDrawing.calloutFrame(size,marks:edge,avoid:[],in:area)
precondition(side == .maxX && card.maxX < edge.minX && area.contains(card),"No room on the right did not flip left")
let earlier = CGRect(x:310,y:0,width:300,height:400)
(card, side) = ScreenDrawing.calloutFrame(size,marks:marks,avoid:[earlier],in:area)
precondition(side != nil && !card.intersects(earlier) && !card.intersects(marks) && area.contains(card),"Callout covered an earlier step")
(card, side) = ScreenDrawing.calloutFrame(size,marks:area.insetBy(dx:10,dy:10),avoid:[],in:area)
precondition(side == nil && card.isNull,"No-room fallback covered its marks")

func buttons(_ v: NSView) -> [NSButton] { v.subviews.compactMap { $0 as? NSButton } }
func labels(_ v: NSView) -> [String] { v.subviews.compactMap { ($0 as? NSTextField)?.stringValue } }
func click(_ b: NSButton) { b.sendAction(b.action,to:b.target) }
var events: [String] = []
func callout(_ text: String, _ step: Int, _ total: Int) -> DrawingCalloutView {
    let s = DrawingCalloutView.size(text,total:total)
    let v = DrawingCalloutView(frame:CGRect(x:0,y:0,width:s.width+24,height:s.height+24),card:CGRect(x:12,y:12,width:s.width,height:s.height),side:.minX,tip:40,text:text,step:step,total:total)
    v.onNext = { events.append("next") }; v.onBack = { events.append("back") }; v.onClose = { events.append("close") }
    return v
}
let first = callout("Complete the square: add 9 to both sides.",1,3)
precondition(labels(first) == ["Step 1 of 3"],"Progress missing")
precondition(buttons(first).first { $0.title == "Back" }?.isEnabled == false && buttons(first).contains { $0.title == "Next" })
click(buttons(first).first { $0.title == "Next" }!); click(buttons(first).first { $0.toolTip == "Close guide" }!)
let last = callout("So x² + 6x = (x + 3)² − 9.",3,3)
click(buttons(last).first { $0.title == "Back" }!); click(buttons(last).first { $0.title == "Done" }!)
precondition(events == ["next","close","back","next"],"Controls did not reach the guide: \(events)")
let single = callout("Click Share.",1,1)
precondition(labels(single).isEmpty && buttons(single).map(\.title) == ["Done"],"A one-step guide shows step controls")
for words in ["a² + b² = c²", "Click Share.", "Complete the square: add 9 to both sides.", "First line\nSecond line"] {
    let card = callout(words,1,3), scroll = card.subviews.compactMap { $0 as? NSScrollView }.first!
    let body = scroll.documentView as! NSTextView
    precondition(body.frame.height <= scroll.contentSize.height,"Short caption needs scrolling: \(words)")
    precondition(body.layoutManager!.usedRect(for:body.textContainer!).maxY <= scroll.contentSize.height,"Short caption is clipped")
}
let long = callout(String(repeating:"A readable instruction needs enough words to wrap. ",count:40),2,4)
let scroll = long.subviews.compactMap { $0 as? NSScrollView }.first!, body = scroll.documentView as! NSTextView
body.layoutManager!.ensureLayout(for:body.textContainer!)
precondition(DrawingCalloutView.size(body.string,total:4).height <= 450 && body.frame.height > scroll.contentSize.height,"Long step text is not scrollable")
let bubble = DrawingCalloutView.bubble(CGRect(x:12,y:12,width:200,height:100),side:.minX,tip:60)
precondition(bubble.boundingBoxOfPath.minX < 12-DrawingCalloutView.notch+1 && bubble.contains(CGPoint(x:8,y:60)),"The notch does not point at the marks")
let plain = DrawingCalloutView.bubble(CGRect(x:12,y:12,width:200,height:100),side:nil,tip:60).boundingBoxOfPath
precondition([plain.minX-12,plain.minY-12,plain.maxX-212,plain.maxY-112].allSatisfy { abs($0) < 0.01 },"A card with no room beside its marks grew a notch")

let pickView = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
pickView.render([DrawingShape(kind:"circle",rect:[100,100,80,20]),DrawingShape(kind:"arrow",points:[[400,110],[200,110]],color:"blue"),
                 DrawingShape(kind:"label",at:[500,500],text:"x"),DrawingShape(kind:"text",text:"board only")],animate:false,previous:nil,step:2)
let ringFrame = ScreenDrawing.ring(CGRect(x:100,y:100,width:80,height:20),circle:true)
precondition(pickView.mark(at:CGPoint(x:ringFrame.midX,y:ringFrame.minY))?.shape == 0,"A ring's stroke takes no click")
precondition(pickView.mark(at:CGPoint(x:140,y:110)) == nil,"A ring took the click meant for its target")
precondition(pickView.mark(at:CGPoint(x:300,y:110)).map { $0.shape == 1 && $0.step == 2 } == true,"An arrow takes no click")
let arrowLayer = pickView.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(arrowLayer.path!.boundingBoxOfPath.height >= 10,"The arrow has no head")
precondition(!pickView.hits.contains { $0.shape == 3 },"Text drew outside its board")
pickView.highlight((2,1)); precondition(pickView.layer!.sublayers!.filter { $0.name == "pick" }.count == 1,"The selected mark has no highlight")
pickView.highlight(nil); precondition(!pickView.layer!.sublayers!.contains { $0.name == "pick" })

for size in ["s","m","l"] { precondition(ScreenDrawing.textSize(size,display:CGRect(x:0,y:0,width:6000,height:4000)) <= 32,"Drawn text is oversized") }
let laptop = ScreenDrawing.textSize(nil,display:CGRect(x:0,y:0,width:1512,height:982)), monitor = ScreenDrawing.textSize(nil,display:CGRect(x:0,y:0,width:1920,height:1080))
precondition(laptop >= 18 && laptop <= 24 && monitor >= 18 && monitor <= 24 && ScreenDrawing.textSize("l",display:.zero) > ScreenDrawing.textSize("s",display:.zero),"Text is not readable: \(laptop) \(monitor)")
if let main = NSScreen.screens.first {
    let d = CGDisplayBounds(main.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! CGDirectDisplayID)
    let near = CGRect(x:d.minX+80,y:d.minY+200,width:200,height:60)
    let worked = [DrawingStep(id:nil,say:"Split it.",target:nil,shapes:[DrawingShape(kind:"text",text:"12x⁵ = 3x² · 4x³")],wait:nil,hit:nil,timeout:nil),
                  DrawingStep(id:nil,say:"Check.",target:nil,shapes:[DrawingShape(kind:"circle",rect:[near.minX,near.minY,near.width,near.height]),
                              DrawingShape(kind:"text",text:"3 · 4 = 12",size:"s")],wait:nil,hit:nil,timeout:nil)]
    let b = ScreenDrawing.board(worked,near:near)!
    precondition(b.lines.map { [$0.step,$0.shape] } == [[0,0],[1,1]] && b.lines[1].rect.minY > b.lines[0].rect.maxY,"Lines are not stacked in order")
    precondition(b.lines.allSatisfy { b.frame.contains($0.rect) } && !b.frame.intersects(near) && b.lines[0].rect.height >= 20,"The board covered its marks or text is small")
    var pinned = worked; pinned[0] = DrawingStep(id:nil,say:"Here.",target:nil,shapes:[DrawingShape(kind:"text",at:[d.minX+300,d.minY+300],text:"x")],wait:nil,hit:nil,timeout:nil)
    precondition(ScreenDrawing.board(pinned,near:near)!.frame.origin == CGPoint(x:d.minX+300,y:d.minY+300),"The board ignored its at")
    let boardView = DrawingView(frame:CGRect(origin:.zero,size:d.size)); boardView.origin = d.origin
    boardView.renderBoard(b.frame,b.lines,current:1,animate:false)
    precondition(boardView.hits.count == 2 && boardView.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!.opacity == 0.7,"Board lines are not selectable, or the earlier line is not quieter")
}

let screenA = CGRect(x:0,y:0,width:1512,height:944), screenB = CGRect(x:1512,y:0,width:1920,height:1050), box = CGRect(x:14,y:800,width:340,height:120)
precondition(ScreenDrawing.clearSpot(box,avoiding:[CGRect(x:600,y:300,width:100,height:100)],in:[screenA,screenB]) == box.origin,"A clear box moved")
let covering = CGRect(x:0,y:780,width:400,height:100), spot = ScreenDrawing.clearSpot(box,avoiding:[covering],in:[screenA,screenB])!
let moved = CGRect(origin:spot,size:box.size)
precondition(!moved.intersects(covering) && screenA.insetBy(dx:8,dy:8).contains(moved) && hypot(spot.x-box.minX,spot.y-box.minY) < 200,"The box did not take the nearest clear spot: \(spot)")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA],in:[screenA,screenB]).map { screenB.contains(CGRect(origin:$0,size:box.size)) } == true,"A covered display did not send the box to the other one")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA,screenB],in:[screenA,screenB]) == nil,"With no room the box must stay")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA,screenB.insetBy(dx:0,dy:100)],in:[screenA,screenB]).map { covered in screenB.contains(CGRect(origin:covered,size:box.size)) } == true,"With no clear room the box must cover the least drawing")
print("Guide geometry: rings outside targets, arrows and labels beside them, callouts beside their marks, Back/Next/Done, selectable marks, text board, box placement")
'''


@unittest.skipUnless(sys.platform == 'darwin','macOS guide geometry check')
class GuideGeometryTests(unittest.TestCase):
    def test_smooth_paths_render_through_samples_without_changing_old_paths(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\nfunc applySharing(_ window: NSWindow) {}\n' + drawing + r'''
NSApplication.shared.setActivationPolicy(.prohibited)
let samples: [[Double]] = [[60,60],[120,180],[180,252],[240,276],[300,252],[360,180],[420,60]]
func shape(_ points: [[Double]], _ mode: [String:Bool] = [:]) -> DrawingShape {
    var data: [String:Any] = ["kind":"path","points":points,"color":"blue"]
    mode.forEach { data[$0.key] = $0.value }
    return try! JSONDecoder().decode(DrawingShape.self,from:JSONSerialization.data(withJSONObject:data))
}
func render(_ shape: DrawingShape) -> (DrawingView, CGPath) {
    let view = DrawingView(frame:CGRect(x:0,y:0,width:480,height:330))
    view.render([DrawingShape(kind:"line",points:[[30,290],[450,290]],color:"white"),
                 DrawingShape(kind:"line",points:[[240,25],[240,310]],color:"white"),shape],animate:false,previous:nil)
    let path = (view.layer!.sublayers!.last as! CAShapeLayer).path!
    return (view,path)
}
let plain = shape(samples), smooth = shape(samples,["smooth":true])
let (before, oldPath) = render(plain), (after, path) = render(smooth)
var corners: [CGPoint] = [], ends: [CGPoint] = [], controls: [(CGPoint,CGPoint,CGPoint)] = []
oldPath.applyWithBlock { e in   // drawn by hand between samples, each sample still exactly on it
    if e.pointee.type == .addLineToPoint { corners.append(e.pointee.points[0]) }
    if e.pointee.type == .addCurveToPoint { corners.append(e.pointee.points[2]) }
}
let lines = samples.dropFirst().filter { s in corners.contains(CGPoint(x:s[0],y:s[1])) }.count
path.applyWithBlock { e in
    if e.pointee.type == .addCurveToPoint {
        let p = e.pointee.points; controls.append((p[0],p[1],p[2])); ends.append(p[2])
    }
}
precondition(lines == samples.count-1 && controls.count == samples.count-1,"smooth samples still render as straight segments")
precondition(ends == samples.dropFirst().map { CGPoint(x:$0[0],y:$0[1]) },"spline does not pass through supplied points")
for i in 1..<controls.count {
    let a = controls[i-1], b = controls[i]
    precondition(abs((a.2.x-a.1.x)-(b.0.x-a.2.x)) < 0.0001 && abs((a.2.y-a.1.y)-(b.0.y-a.2.y)) < 0.0001,"spline has a corner at a sample")
}
let occupied = ScreenDrawing.markBounds([smooth])[0]
precondition(occupied.contains(path.boundingBoxOfPath),"spline escapes reserved mark bounds")
let cubic = shape([[0,0],[0,100],[100,100],[100,0]],["curve":true])
precondition(render(cubic).1.boundingBoxOfPath.height == 75,"explicit cubic payload changed")
for points in [[[0.0,0],[100,100]], [[0,0],[0,0],[100,100]], [[0,0],[0,0],[0,0]]] {
    let p = render(shape(points,["smooth":true])).1
    precondition(!p.boundingBoxOfPath.isInfinite,"short or repeated samples produced invalid geometry")
}
let target = DrawingWindow(pid:1,windowID:"1",windowFrame:[0,0,480,330])
func valid(_ s: DrawingShape) -> Bool {
    ScreenDrawing.valid(DrawingRequest(steps:[DrawingStep(id:nil,say:"A curve.",target:nil,shapes:[s],wait:nil,hit:nil,timeout:nil)],teaching:true,target:target,state:"fixture",receipt:nil))
}
precondition(valid(smooth) && valid(plain) && valid(cubic))
precondition(!valid(shape(samples,["smooth":true,"curve":true])),"ambiguous modes accepted")
let line = try! JSONDecoder().decode(DrawingShape.self,from:Data("{\"kind\":\"line\",\"points\":[[0,0],[1,1]],\"smooth\":true}".utf8))
precondition(!valid(line),"line silently accepted smoothing")
for (name,view) in [("before",before),("after",after)] {
    let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:960,pixelsHigh:660,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let context = NSGraphicsContext(bitmapImageRep:image)!.cgContext
    context.setFillColor(NSColor(calibratedWhite:0.08,alpha:1).cgColor); context.fill(CGRect(x:0,y:0,width:960,height:660))
    context.scaleBy(x:2,y:2); context.translateBy(x:0,y:330); context.scaleBy(x:1,y:-1)
    view.layer!.render(in:context)
    print("SMOOTH_DRAW_PNG \(name) \(image.representation(using:.png,properties:[:])!.base64EncodedString())")
}
print("smooth drawing geometry ok")
''',timeout=20)
        self.assertIn('smooth drawing geometry ok',out)
        print(out,flush=True)   # runner stops the VM; export render artifacts through stdout

    def test_marks_and_callouts_stay_clear_of_targets(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        self.assertIn('Guide geometry',run_swift(self,GEOMETRY.replace('__DRAWING__',drawing),timeout=20))
