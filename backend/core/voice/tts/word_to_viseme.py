"""
Grapheme-to-phoneme-to-viseme heuristic for edge-tts / ElevenLabs.

Converts English words into a sequence of extended viseme keys
(sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, I, O, U).

Not a full G2P — just enough to map word timing to plausible mouth shapes.
"""

import re 


_PHONEME_TO_VISEME ={
"AA":"aa","AE":"E","AH":"aa","AO":"O","AW":"aa",
"AY":"aa","EH":"E","ER":"RR","EY":"E","IH":"I",
"IY":"I","OW":"O","OY":"O","UH":"U","UW":"U",
"B":"PP","CH":"CH","D":"DD","DH":"TH","F":"FF",
"G":"kk","HH":"aa","JH":"CH","K":"kk","L":"DD",
"M":"PP","N":"nn","NG":"nn","P":"PP","R":"RR",
"S":"SS","SH":"CH","T":"DD","TH":"TH","V":"FF",
"W":"U","Y":"I","Z":"SS","ZH":"CH",
}


_LETTER_VISEME ={
"a":"aa","b":"PP","c":"kk","d":"DD","e":"E",
"f":"FF","g":"kk","h":"aa","i":"I","j":"CH",
"k":"kk","l":"DD","m":"PP","n":"nn","o":"O",
"p":"PP","q":"kk","r":"RR","s":"SS","t":"DD",
"u":"U","v":"FF","w":"U","x":"kk","y":"I",
"z":"SS",
}


_DIGRAPHS =[
("sh","CH"),("ch","CH"),("th","TH"),("ph","FF"),
("wh","U"),("ck","kk"),("ng","nn"),("nk","nn"),
("qu","kk"),("wr","RR"),("gn","nn"),("kn","nn"),
("mb","PP"),("mn","nn"),
]


_VOWEL_GROUPS =[
("oo","U"),("ou","aa"),("ow","O"),("oi","O"),
("oy","O"),("ee","I"),("ea","I"),("ei","E"),
("ie","I"),("ai","E"),("ay","aa"),("au","O"),
("aw","O"),("ue","U"),("ew","U"),("ey","E"),
]


def word_to_visemes (word :str )->list [str ]:
    """
    Convert an English word to a list of extended viseme keys.

    Returns 1-3 visemes per syllable, roughly proportional to phoneme count.
    Not linguistically accurate — just plausible mouth movement timing.
    """
    w =re .sub (r"[^a-z]","",word .lower ())
    if not w :
        # Word was entirely non-alpha (e.g., "123", "C++")
        # Map digits to "aa" viseme, rest to "sil"
        if word :
            return ["aa"] if word .isdigit ()else ["sil"]
        return ["sil"]

    visemes =[]
    i =0 
    while i <len (w ):
        matched =False 

        for pattern ,vis in _DIGRAPHS :
            if w [i :i +len (pattern )]==pattern :
                visemes .append (vis )
                i +=len (pattern )
                matched =True 
                break 
        if matched :
            continue 

        for pattern ,vis in _VOWEL_GROUPS :
            if w [i :i +len (pattern )]==pattern :
                visemes .append (vis )
                i +=len (pattern )
                matched =True 
                break 
        if matched :
            continue 

        ch =w [i ]
        visemes .append (_LETTER_VISEME .get (ch ,"sil"))
        i +=1 

    collapsed =[]
    for v in visemes :
        if not collapsed or collapsed [-1 ]!=v :
            collapsed .append (v )


    syllable_count =max (1 ,len (re .findall (r'[aeiouy]+',w )))
    while len (collapsed )<syllable_count :

        vowel_vis =_LETTER_VISEME .get (
        next ((c for c in w if c in "aeiouy"),"a"),
        "aa"
        ) if w else "aa"
        collapsed .insert (len (collapsed )//2 ,vowel_vis )

    return collapsed if collapsed else ["sil"]


def viseme_schedule_from_words (word_boundaries :list [dict ])->list [dict ]:
    """
    Convert word boundaries into a viseme schedule.

    Args:
        word_boundaries: [{"text": "Hello", "start": 0.12, "end": 0.45}, ...]

    Returns:
        [{"viseme": "aa", "start": 0.12, "duration": 0.05}, ...]
    """
    schedule =[]
    for wb in word_boundaries :
        text =wb ["text"]
        start =wb ["start"]
        end =wb ["end"]
        duration =end -start 

        visemes =word_to_visemes (text )
        if not visemes :
            continue 

        vis_dur =duration /len (visemes )
        t =start 
        for vis in visemes :
            schedule .append ({
            "viseme":vis ,
            "start":round (t ,4 ),
            "duration":round (vis_dur ,4 ),
            })
            t +=vis_dur 

    filled =[]
    for i ,entry in enumerate (schedule ):
        if i >0 :
            gap =entry ["start"]-(filled [-1 ]["start"]+filled [-1 ]["duration"])
            if gap >0.0 :
                filled .append ({
                "viseme":"sil",
                "start":round (filled [-1 ]["start"]+filled [-1 ]["duration"],4 ),
                "duration":round (gap ,4 ),
                })
        filled .append (entry )

    return filled 

build_viseme_schedule =viseme_schedule_from_words 
