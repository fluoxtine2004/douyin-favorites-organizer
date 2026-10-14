# -*- coding: utf-8 -*-
"""待归类分类器 v2：严格顺序 + 强特征词 + 反向否决"""
import json, re, sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

d = json.load(open('data/favorites.json', encoding='utf-8'))
cj = json.load(open('config/categories.json', encoding='utf-8'))
mp = cj['mapping']
ex = set(str(x) for x in (json.load(open('data/excluded.json', encoding='utf-8')).get('ids') or []))

# v2：改用「强特征词」而非泛词。每条规则必须有明确的、几乎不会出现在别处的词。
STRONG = [
    # ---- 学习：技术/学术/语言学习 ----
    ('学习', r'(GitHub|Git\s*&|DeepSeek|GPT|大模型|vibe\s?coding|agent|skill|Python|Java|前端|后端|算法|代码|编程|开源项目|部署|服务器|API|数据库|技术栈|计算机|IT巨|科研|论文|学术|导师|博士|硕士|研究生|保研|考研|留学申请|公开课|网课|英语|四级|六级|专八|雅思|托福|口语|语法|单词|考研英语|政治|数学|物理|化学|生物|学科|讲座|课程|教程|教学|知识|干货|入门|扫盲|使用教程|操作|配置|技巧|方法论|笔记|考试|刷题|真题|单词书|Codex|Claude|Gemini|Cursor|TRAE|服务器|运维)'),
    # ---- 旅行：目的地/出行 ----
    ('旅游', r'(旅游攻略|旅行攻略|自由行|穷游|背包客|自驾游|自驾|vlog.*(西藏|新疆|云南|三亚|西藏|内蒙|青海)|西藏|新疆|云南|三亚|青海|内蒙|敦煌|布达拉|冰岛|印尼|巴厘岛|马尔代夫|泰国|日本|韩国|新加坡|马来西亚|欧洲行|机票|酒店预订|民宿|青旅|签证|免签|打卡|景点|徒步|露营|登山|徒步|citywalk|看世界|旅行vlog|旅游vlog|路线规划|穷游必备|出境游|跟团)'),
    # ---- 美食 ----
    ('美食', r'(美食|探店|餐厅|好吃|食谱|菜谱|烹饪|做饭|厨房|烘焙|甜品|提拉米苏|咖啡店|咖啡师|早餐|午餐|晚餐|火锅|烧烤|面馆|食堂|food|水果|餐桌|一人食|漂亮饭|摆摊.*吃|餐厅测评|美食推荐)'),
    # ---- 生活：健身/宠物/穿搭/家居/音乐器乐 ----
    ('生活', r'(健身|增肌|减脂|瘦脸|瑜伽|普拉提|跑步|马拉松|游泳|篮球|羽毛球|健身餐|蛋白粉|肌肉|腹肌|体态|骨盆|拉伸|跟练|运动|养生|睡眠|护肤|化妆|穿搭|OOTD|ootd|时尚|美妆|发型|美甲|收纳|家居|装修|除甲醛|宠物|猫咪|狗狗|猫猫|狗狗|萌宠|钢琴|吉他|翻唱|乐器|乐队|演唱会|音乐现场|华语乐坛|民谣|说唱|rap|电音|白噪音|助眠|冥想|ASMR|钢琴曲|乐理|唱歌)'),
    # ---- 成长：思维/职场/商业/心理/理财/沟通 ----
    ('成长', r'(认知|思维|逻辑谬误|批判性思维|心智|决策|理性|底层逻辑|原则|方法论|沟通|表达|情商|说话技巧|演讲|口才|写作|读书|书单|认知思维|人性|社会|心理|心理学|焦虑|内耗|情绪|emo|孤独|迷茫|意义|幸福|哲学|历史|法律|政治|社会达尔文|人性洞察|职场|求职|简历|面试|实习|offer|秋招|春招|大厂|打工|副业|创业|赚钱|搞钱|商业|营销|自媒体|IP|流量|粉丝|变现|电商|直播带货|理财|投资|基金|股票|炒股|财经|财商|钱|财务|存钱|攒钱|穷|富|房产|资产|经济|管理|领导|执行|效率|时间管理|专注|自律|拖延|习惯|复利|成长|普通人如何|内耗|关系|婚姻|恋爱|原生家庭|父母|社交|人脉|贵人|向上管理|学历|二本|藤校|双非|应届生|毕业生|失业|35岁|中年)'),
]

# 强否决：命中这些词说明整体大类判断要改
VETO = {
    '美食': re.compile(r'(投资|理财|基金|股票|求职|职场|vlog|vlog日常|日常vlog|教程|英语|学习|博士|硕士|毕业|创业|生啤|咖啡店|旅居)'),
    '旅游': re.compile(r'(租房|话术|优衣库|折扣|薅羊毛|消费|商业|伴侣|情侣|记录13年|政|学习|教程|英语)'),
    '学习': re.compile(r'(赴港|苹果手机|游戏测评|煤炭镇|本体面|澳洲|火锅|美食|旅行|旅游|vlog|演唱会|钢琴)'),
    '生活': re.compile(r'(移民|美国华人|学历|工作|收入|二本|藤校|高考|对谈)'),
}

NOISE = re.compile(r'(风景|景色|美景|日落|云海|大海|星空|彩虹|壁纸|氛围感|随手拍|生活碎片|纯音乐|助眠|白噪音|vlog日常|plog|胶片|ccd|CCD|相机)')

def pick(title, transcript):
    t = title or ''
    for major, pat in STRONG:
        if re.search(pat, t, re.I):
            veto = VETO.get(major)
            if veto and veto.search(t):
                continue
            return major, 'title'
    # 标题无强信号 → 看逐字稿，但只认非常明确的知识词
    bpat = re.compile(r'(教程|教你|如何用|怎么用|使用方法|部署|安装|配置|代码|编程|开发|算法原理|开源|GitHub|笔记整理|知识分享|心理学|认知科学|经济学|投资理财|求职|简历|面试技巧|健身增肌|减脂方法)')
    b = transcript or ''
    if bpat.search(b[:1200]):
        m = re.search(r'(教程|教你|如何用|怎么用|使用方法|部署|安装|配置|代码|编程|开发|开源|GitHub)', b[:1200])
        if m:
            key = m.group(1)
            if key in ('部署','安装','配置','代码','编程','开发','开源','GitHub','使用方法','如何用','怎么用','教你'):
                return '学习', 'transcript'
            if key in ('教程',):
                return '学习', 'transcript'
        if re.search(r'(心理学|认知科学|经济学|投资理财|求职|简历|面试技巧|健身增肌|减脂方法)', b[:1200]):
            if re.search(r'(心理学|认知科学|经济学)', b[:1200]): return '成长', 'transcript'
            if re.search(r'(投资理财|求职|简历|面试技巧)', b[:1200]): return '成长', 'transcript'
            if re.search(r'(健身增肌|减脂方法)', b[:1200]): return '生活', 'transcript'
    return None, None

result = {}
stats = Counter()
src = Counter()
unclassified = []
for fo in d['folders']:
    for v in fo.get('videos', []):
        vid = str(v['id'])
        if vid in ex:
            continue
        if mp.get(fo['name']) and mp[fo['name']] != '待归类':
            continue
        skip = False
        for maj, kws in cj.get('rules', {}).items():
            if any(k in fo['name'] for k in kws):
                skip = True
        if skip:
            continue
        title = str(v.get('title') or '')
        tr = str(v.get('transcript') or '')
        major, s = pick(title, tr)
        if major and not NOISE.search(title):
            result[vid] = major
            stats[major] += 1
            src[s] += 1
        else:
            unclassified.append({'id': vid, 'title': title[:80], 'folder': fo['name']})

print('=== v2 分类结果 ===')
tot = 0
for k, n in stats.most_common():
    print('  %-6s %4d' % (k, n)); tot += n
print('  ---- 已分类: %d / 保留待归类: %d' % (tot, len(unclassified)))
print('  信号来源: %s' % dict(src))
json.dump(result, open('data/video_major_pending.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(unclassified, open('data/_pend_unclassified.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('已写入 data/video_major_pending.json（仍未合并到 video_major.json）')
