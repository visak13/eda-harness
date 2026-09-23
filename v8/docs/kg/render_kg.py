from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

ROOT = Path(__file__).resolve().parent
S = 2
BG = '#F6F8FB'
INK = '#172B43'
MUTED = '#455970'
BLUE = '#215BB3'
TEAL = '#147568'
GREY = '#66717F'
AMBER = '#895414'
FONTS = {}

def font(size, bold=False):
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf', size*S)
    return FONTS[key]

class Canvas:
    def __init__(self, w, h):
        self.im = Image.new('RGB', (w*S,h*S), BG)
        self.d = ImageDraw.Draw(self.im)
        self.w,self.h=w,h
    def box(self, rect, fill='white', outline='#CFD9E5', radius=18, width=2):
        self.d.rounded_rectangle(tuple(int(v*S) for v in rect),radius=radius*S,fill=fill,outline=outline,width=width*S)
    def text(self,x,y,s,size=28,bold=False,color=INK):
        for i,line in enumerate(s.split('\n')):
            assert self.d.textlength(line,font=font(size,bold)) <= (self.w-x-20)*S, (s,x)
            self.d.text((x*S,(y+i*(size+9))*S),line,font=font(size,bold),fill=color,anchor='lt')
    def line(self, pts, color=BLUE, width=3, dash=False, arrow=True):
        p=[(int(x*S),int(y*S)) for x,y in pts]
        if dash:
            for a,b in zip(p,p[1:]):
                dist=math.dist(a,b)
                for t in range(0,int(dist),18*S):
                    end=min(t+10*S,dist)
                    self.d.line([(a[0]+(b[0]-a[0])*t/dist,a[1]+(b[1]-a[1])*t/dist),(a[0]+(b[0]-a[0])*end/dist,a[1]+(b[1]-a[1])*end/dist)],fill=color,width=width*S)
        else:
            self.d.line(p,fill=color,width=width*S,joint='curve')
        if arrow:
            a,b=p[-2:]; ang=math.atan2(b[1]-a[1],b[0]-a[0]); z=13*S
            self.d.polygon([b,(b[0]-z*math.cos(ang-.5),b[1]-z*math.sin(ang-.5)),(b[0]-z*math.cos(ang+.5),b[1]-z*math.sin(ang+.5))],fill=color)
    def label(self,x,y,s,color=BLUE,size=26,fill=BG):
        w=self.d.textlength(s,font=font(size,True))/S
        self.box((x-7,y-5,x+w+7,y+size+7),fill,fill,6)
        self.text(x,y,s,size,True,color)
    def save(self,name):
        self.im.resize((self.w,self.h),Image.Resampling.LANCZOS).save(ROOT/name)

def structure():
    c=Canvas(2000,1400)
    c.text(60,42,'How the agent remembers past decisions',54,True)
    c.text(60,118,'Small records preserve the rule, its evidence and its origin. Links keep them connected.',29,color=MUTED)
    c.box((40,190,1350,950),'#EDF3FC','#A8BFDF',24)
    c.text(75,218,'EPIC A  ·  one project’s work',32,True,BLUE)
    c.text(750,224,'Decisions and claims stay here',28,color=BLUE)
    c.box((80,285,650,720))
    c.text(105,310,'Decision',38,True,BLUE)
    c.text(105,364,'One-sentence rule',30,True)
    c.text(105,411,'Why / detail\nBinding: yes or no\nReplaces: earlier decision IDs\nSource: message, doc or attachment\nScope: epic, or a ticket in that epic\nState: live / replaced / withdrawn',27)
    c.box((740,285,1310,720))
    c.text(765,310,'Claim',38,True,BLUE)
    c.text(765,364,'One-sentence statement',30,True)
    c.text(765,411,'Basis: assumption / measured / ruled\nEvidence: attachment, check or commit\nSource: original message or document\nScope: epic, or a ticket in that epic',27)
    c.box((760,582,1290,697),'#EDF3FC','#EDF3FC',10)
    c.text(775,598,'Confirmed only with evidence\nand a measured or ruled basis.',27,True)
    c.box((80,825,445,920),'#F1F3F6','#C5CCD5')
    c.text(102,842,'Earlier decision',29,True)
    c.text(102,881,'Kept as replaced history',26,color=MUTED)
    c.box((740,825,1310,920),'white','#B4C6DE')
    c.text(765,842,'Epic A / its ticket',29,True)
    c.text(765,881,'The work this record belongs to',26,color=MUTED)
    c.line([(270,720),(270,825)])
    c.label(288,761,'replaces',fill='#EDF3FC')
    c.line([(600,720),(600,774),(800,774),(800,825)])
    c.label(609,735,'decides',fill='#EDF3FC')
    c.line([(1160,720),(1160,825)],GREY,dash=True)
    c.label(1175,761,'part_of',GREY,fill='#EDF3FC')
    c.line([(1385,210),(1385,948)],GREY,5,False,False)
    c.box((1440,190,1940,395),'#F0F2F5','#BCC5CF')
    c.text(1465,217,'EPIC B  ·  separate work',30,True)
    c.text(1465,269,'Its own decisions and claims.\nEpic A’s rules never enter\nEpic B’s lookup.',28)
    c.box((1440,460,1940,950),'#EAF6F1','#86BAAB',22)
    c.text(1465,486,'Lesson',38,True,TEAL)
    c.text(1465,546,'Shared across epics',30,True,TEAL)
    c.text(1465,596,'One-sentence takeaway\nDomain / topic\nEvidence: defect, rework or ruling\nUsed / helped / harmed counts\nState: live or retired',27)
    c.text(1465,813,'Either epic can find it\nby subject or topic.\nNo epic scope field.',28,True,TEAL)
    c.line([(1670,460),(1670,395)],TEAL,dash=True)
    c.label(1710,416,'shared',TEAL)
    c.line([(1440,870),(1310,870)],TEAL,dash=True)
    # Written connections to the sources; arrowheads follow stored from/to direction.
    c.line([(80,505),(55,505),(55,1000),(275,1000),(275,1070)])
    c.label(94,984,'came_from')
    c.line([(520,720),(520,1070)])
    c.label(535,1006,'must_follow')
    c.line([(1310,500),(1330,500),(1330,1000),(1040,1000),(1040,1070)])
    c.label(1068,984,'proves')
    c.line([(1690,950),(1690,1070)],TEAL)
    c.label(1710,994,'learned_from',TEAL)
    c.box((80,1070,650,1230))
    c.text(105,1091,'Thread messages & design docs',30,True)
    c.text(105,1138,'Decision notes (ADRs), attachments\nThe original rule or required reference',27)
    c.box((740,1070,1310,1230))
    c.text(765,1091,'Reviews, checks & commits',30,True)
    c.text(765,1138,'Evidence a claim points to\n“proves” stores claim → evidence',27)
    c.box((1440,1070,1940,1230))
    c.text(1465,1091,'Review outcomes',30,True)
    c.text(1465,1138,'Defects, rework and rulings\nEvidence behind a lesson',27)
    c.line([(1020,1230),(1020,1330),(1210,1330)],GREY,dash=True)
    c.label(1045,1283,'touches',GREY)
    c.box((1210,1290,1440,1367),'#F0F2F5','#BCC5CF')
    c.text(1230,1310,'Changed file',28,True)
    c.text(760,1285,'Commit',27,color=GREY)
    c.line([(80,1298),(150,1298)],BLUE)
    c.text(168,1280,'Named links = kglink records',27,True)
    c.line([(80,1344),(150,1344)],GREY,dash=True)
    c.text(168,1326,'Grey links = derived connections',27,color=GREY)
    c.text(1490,1280,'Scope wall: rules stay local.\nOnly lessons are shared.',27,True)
    c.save('kg-structure.png')

def flow():
    c=Canvas(2000,1200)
    c.text(60,42,'One question → a small memory pack',54,True)
    c.text(60,119,'The agent reads the relevant past decisions, with evidence and a record of what was left out.',29,color=MUTED)
    nodes=[(60,215,375,510),(425,215,840,510),(900,215,1380,510),(1440,215,1940,510)]
    for r in nodes:c.box(r)
    for a,b in [(375,425),(840,900),(1380,1440)]:c.line([(a,355),(b,355)])
    c.text(83,240,'1  Ask',34,True,BLUE)
    c.text(83,302,'An agent (seat)\nasks a question\nfor its own epic.',29)
    c.text(83,440,'One lookup call',27,True)
    c.text(449,240,'2  Set aside rules',33,True,BLUE)
    c.text(449,302,'Always include live binding\nand must-follow decisions.\nText only, never cut.',27)
    c.box((443,424,822,493),'#FFF1DA','#FFF1DA',9)
    c.text(454,436,'They take what they need;\nanswers absorb the rest.',26,True,AMBER)
    c.text(924,240,'3  Find starting records',32,True,BLUE)
    c.text(924,304,'Keyword search (FTS5)\n+ meaning search, if available\n   (dense embeddings)',27)
    c.text(924,422,'Merge the two rankings (RRF).\nThese matches are the “seeds”.',27,True)
    c.text(1464,240,'4  Follow connections',33,True,BLUE)
    c.text(1464,302,'Walk links up to 2 steps (hops).\nStay inside the epic;\nshared lessons are the exception.',27)
    c.text(1464,427,'Source and replacement links\nare not walked.',27,color=MUTED)
    c.line([(1690,510),(1690,580)])
    c.box((1440,580,1940,810))
    c.text(1464,604,'5  Rank useful records',33,True,BLUE)
    c.text(1464,661,'Direct matches first; then linked hits.\nUse relevance, age and usefulness.\nDrop inactive records and weak hits.',26)
    c.line([(1440,698),(1360,698)])
    c.box((560,580,1360,1090),'white','#8FAACD',22,3)
    c.text(585,605,'6  Fit the pack to 16,000 bytes',35,True,BLUE)
    c.text(585,662,'Rules, relevant answers and shared lessons share one budget.',26)
    # To-scale maximum allocations; middle expands when either reserve is not used.
    c.box((585,716,765,786),'#DCE9FB','#DCE9FB',0)
    c.box((765,716,1170,786),'#EDF0F5','#EDF0F5',0)
    c.box((1170,716,1305,786),'#D8EFE5','#D8EFE5',0)
    c.text(610,733,'rules',30,True,BLUE)
    c.text(805,733,'answers: the rest',29,True)
    c.text(1185,733,'1,500',29,True,TEAL)
    c.text(585,817,'Rules: text only, never cut; their size is reported.',27,True,BLUE)
    c.text(585,860,'Lessons: up to 1,500 bytes and 3 records.',27,True,TEAL)
    c.text(585,903,'Answers use the rest, including unused allowances.',27)
    c.text(585,946,'Few strong matches? Add unconfirmed source excerpts.',26)
    c.text(585,1004,'The byte limit counts record data, including its labels.\nThe receipt and display headings sit outside that count.',26,color=MUTED)
    c.line([(560,698),(490,698)])
    c.box((60,580,490,1090),'#EAF1FC','#B4C6DE',22)
    c.text(84,605,'7  The seat reads',33,True,BLUE)
    c.text(84,670,'≈18 records',49,True)
    c.text(84,736,'instead of a\n400-message thread',30,True)
    c.text(84,835,'An illustration, not a fixed\nrecord count. Size varies\nwith the question and text.',27)
    c.text(84,961,'Each record carries its ID\nand confirmation / age labels.',26)
    c.box((1440,860,1940,1090),'#FFF6E8','#D8BA8F',18)
    c.text(1464,883,'Receipt: what was cut',31,True,AMBER)
    c.text(1464,936,'Counts by type + record IDs\nBytes the rules took (always_bytes)\nRead a cut record by its ID',26)
    c.line([(1360,950),(1440,950)],AMBER)
    c.text(60,1132,'Binding text is never cut (since 736d248); ranked answers take what is left.',27,True,AMBER)
    c.save('kg-lookup.png')

if __name__ == '__main__':
    structure()
    flow()
    for name,size in [('kg-structure.png',(2000,1400)),('kg-lookup.png',(2000,1200))]:
        with Image.open(ROOT/name) as im:
            im.load()
            assert im.size == size
            im.resize((1300,round(im.height*1300/im.width)),Image.Resampling.LANCZOS).save(ROOT/(name.removesuffix('.png')+'-laptop.png'))
        print(f'{name}: opens correctly, {size[0]} x {size[1]}')
