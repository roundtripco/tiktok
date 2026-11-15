"""صور تجريبية (رسومات بسيطة) بدل صور العقار الحقيقية، وشعار مكتب وهمي."""

from aqarbot.render import Renderer

_PAGE = "<html><body style='margin:0'>{svg}</body></html>"

SCENES = {
    "building": """
<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='960' viewBox='0 0 1280 960'>
 <defs><linearGradient id='s' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#8fc3ea'/><stop offset='1' stop-color='#e8f3fb'/></linearGradient></defs>
 <rect width='1280' height='960' fill='url(#s)'/>
 <circle cx='1080' cy='170' r='70' fill='#fff3c4'/>
 <rect x='0' y='800' width='1280' height='160' fill='#d9cbb0'/>
 <rect x='330' y='170' width='620' height='640' fill='#efe6d6'/>
 <rect x='330' y='170' width='620' height='34' fill='#c9b48f'/>
 <g fill='#5f8fb3'>
  <rect x='380' y='240' width='110' height='120' rx='4'/><rect x='585' y='240' width='110' height='120' rx='4'/><rect x='790' y='240' width='110' height='120' rx='4'/>
  <rect x='380' y='410' width='110' height='120' rx='4'/><rect x='585' y='410' width='110' height='120' rx='4'/><rect x='790' y='410' width='110' height='120' rx='4'/>
  <rect x='380' y='580' width='110' height='120' rx='4'/><rect x='790' y='580' width='110' height='120' rx='4'/>
 </g>
 <rect x='585' y='600' width='110' height='210' fill='#6b4f3a'/>
 <rect x='150' y='620' width='18' height='190' fill='#7a5a3a'/><circle cx='159' cy='590' r='80' fill='#5e9b5a'/>
 <rect x='1110' y='640' width='18' height='170' fill='#7a5a3a'/><circle cx='1119' cy='610' r='70' fill='#6aa864'/>
</svg>""",
    "living": """
<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='960' viewBox='0 0 1280 960'>
 <rect width='1280' height='960' fill='#f3ece2'/>
 <rect y='700' width='1280' height='260' fill='#c8ab88'/>
 <rect x='760' y='140' width='380' height='380' fill='#bfe0f5' stroke='#fff' stroke-width='18'/>
 <line x1='950' y1='140' x2='950' y2='520' stroke='#fff' stroke-width='12'/>
 <rect x='160' y='200' width='300' height='200' fill='#d98c5f'/><rect x='180' y='220' width='260' height='160' fill='#f2c39c'/>
 <rect x='140' y='520' width='620' height='170' rx='30' fill='#4f6d7a'/>
 <rect x='120' y='600' width='660' height='120' rx='30' fill='#5c7f8e'/>
 <rect x='200' y='540' width='150' height='90' rx='20' fill='#e8d6b5'/><rect x='560' y='540' width='150' height='90' rx='20' fill='#e8d6b5'/>
 <ellipse cx='640' cy='860' rx='260' ry='50' fill='#a98d6b'/>
 <rect x='880' y='560' width='26' height='150' fill='#7a5a3a'/><circle cx='893' cy='540' r='60' fill='#5e9b5a'/>
</svg>""",
    "kitchen": """
<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='960' viewBox='0 0 1280 960'>
 <rect width='1280' height='960' fill='#eef1f2'/>
 <rect y='760' width='1280' height='200' fill='#b9b2a6'/>
 <rect x='80' y='120' width='1120' height='220' fill='#ffffff' stroke='#d5dadd' stroke-width='6'/>
 <g stroke='#d5dadd' stroke-width='6'><line x1='360' y1='120' x2='360' y2='340'/><line x1='640' y1='120' x2='640' y2='340'/><line x1='920' y1='120' x2='920' y2='340'/></g>
 <rect x='80' y='520' width='1120' height='240' fill='#ffffff' stroke='#d5dadd' stroke-width='6'/>
 <rect x='60' y='490' width='1160' height='36' fill='#3d4a52'/>
 <rect x='520' y='420' width='240' height='70' fill='#9aa5ab'/>
 <circle cx='320' cy='460' r='34' fill='#d97a4a'/><rect x='880' y='400' width='120' height='90' rx='12' fill='#5f8fb3'/>
 <g stroke='#d5dadd' stroke-width='6'><line x1='360' y1='526' x2='360' y2='760'/><line x1='640' y1='526' x2='640' y2='760'/><line x1='920' y1='526' x2='920' y2='760'/></g>
</svg>""",
    "bedroom": """
<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='960' viewBox='0 0 1280 960'>
 <rect width='1280' height='960' fill='#e9eef3'/>
 <rect y='720' width='1280' height='240' fill='#b79e82'/>
 <rect x='320' y='300' width='640' height='200' rx='20' fill='#7d8fa3'/>
 <rect x='280' y='480' width='720' height='240' rx='24' fill='#ffffff'/>
 <rect x='280' y='560' width='720' height='160' rx='24' fill='#c7d6e4'/>
 <rect x='360' y='430' width='210' height='90' rx='26' fill='#f4efe6'/><rect x='710' y='430' width='210' height='90' rx='26' fill='#f4efe6'/>
 <rect x='110' y='560' width='130' height='160' fill='#8a6a4c'/><circle cx='175' cy='520' r='36' fill='#f6d68b'/>
 <rect x='1040' y='560' width='130' height='160' fill='#8a6a4c'/><circle cx='1105' cy='520' r='36' fill='#f6d68b'/>
</svg>""",
}

LOGO = """
<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400' viewBox='0 0 400 400'>
 <rect width='400' height='400' fill='#fff'/>
 <circle cx='200' cy='200' r='170' fill='#1E6B52'/>
 <path d='M110 215 L200 130 L290 215 V290 H110 Z' fill='#fff'/>
 <rect x='180' y='235' width='40' height='55' fill='#1E6B52'/>
</svg>"""


async def make_images(renderer: Renderer) -> tuple[dict[str, bytes], bytes]:
    scenes = {k: await renderer.image(_PAGE.format(svg=v), 1280, 960) for k, v in SCENES.items()}
    logo = await renderer.image(_PAGE.format(svg=LOGO), 400, 400)
    return scenes, logo
