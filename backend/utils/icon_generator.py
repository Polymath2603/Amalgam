"""
Character icon generation — letter-based PNG (PIL) and VRM-based (Node.js).
Extracted from server.py into its own module.
"""
import os 
import asyncio 
import logging 
from k_core .paths import CHARACTERS_DIR ,PROJECT_ROOT 

logger =logging .getLogger (__name__ )

PALETTE =[
"#6c5ce7","#0984e3","#00b894","#e17055","#fd79a8",
"#f39c12","#00cec9","#e74c3c","#2ecc71","#3498db",
"#9b59b6","#1abc9c","#d35400","#c0392b","#16a085",
"#8e44ad","#27ae60","#2980b9","#f1c40f","#e67e22",
"#e84393","#00b894","#6c5ce7","#fd79a8","#0984e3",
"#00cec9","#e17055","#f39c12","#e74c3c","#2ecc71",
]


def _generate_letter_icon (name :str ,letter :str ,color_hex :str ,output_path :str ):
    """Generate a 96x96 PNG icon with a colored background and letter."""
    try :
        from PIL import Image ,ImageDraw ,ImageFont 
    except ImportError :
        return False 
    SIZE =96 
    def hex_to_rgb (h ):
        h =h .lstrip ('#')
        return tuple (int (h [i :i +2 ],16 )for i in (0 ,2 ,4 ))
    def lighten (c ,f =0.3 ):
        return tuple (int (v +(255 -v )*f )for v in c )
    def darken (c ,f =0.3 ):
        return tuple (int (v *(1 -f ))for v in c )
    bg =hex_to_rgb (color_hex )
    img =Image .new ('RGBA',(SIZE ,SIZE ),(0 ,0 ,0 ,0 ))
    draw =ImageDraw .Draw (img )
    draw .rounded_rectangle ([0 ,0 ,SIZE -1 ,SIZE -1 ],radius =16 ,fill =bg )
    highlight =lighten (bg ,0.25 )
    draw .rounded_rectangle ([2 ,2 ,SIZE -3 ,SIZE -3 ],radius =14 ,fill =highlight +(30 ,))
    try :
        font =ImageFont .truetype ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",44 )
    except (IOError ,OSError ):
        font =ImageFont .load_default ()
    bbox =draw .textbbox ((0 ,0 ),letter ,font =font )
    tw ,th =bbox [2 ]-bbox [0 ],bbox [3 ]-bbox [1 ]
    x =(SIZE -tw )/2 -bbox [0 ]
    y =(SIZE -th )/2 -bbox [1 ]-2 
    draw .text ((x +1 ,y +1 ),letter ,fill =darken (bg ,0.4 )+(100 ,),font =font )
    draw .text ((x ,y ),letter ,fill =(255 ,255 ,255 ,230 ),font =font )
    img .save (output_path ,'PNG')
    return True 


async def generate_missing_icons ():
    """Generate icons for characters missing icon.png. Tries VRM renderer first, falls back to letters."""
    if not os .path .exists (CHARACTERS_DIR ):
        return 
    missing =[]
    for d in sorted (os .listdir (CHARACTERS_DIR )):
        char_path =os .path .join (CHARACTERS_DIR ,d )
        if os .path .isdir (char_path )and not os .path .exists (os .path .join (char_path ,"icon.png")):
            missing .append (d )
    if not missing :
        return 
    logger .debug (f"Missing icons for {len (missing )} character(s): {', '.join (missing )}")

    import shutil 
    node =shutil .which ("node")
    vrm_script =os .path .join (PROJECT_ROOT ,"scripts","generate-icons-vrm.js")
    if node and os .path .exists (vrm_script ):
        try :
            proc =await asyncio .create_subprocess_exec (
            node ,vrm_script ,
            stdout =asyncio .subprocess .PIPE ,
            stderr =asyncio .subprocess .PIPE ,
            cwd =PROJECT_ROOT 
            )
            stdout ,stderr =await asyncio .wait_for (proc .communicate (),timeout =300 )
            if proc .returncode ==0 :
                logger .debug ("VRM icon generation complete")
                return 
            else :
                logger .warning (f"VRM icon generation failed (exit {proc .returncode })")
        except Exception as e :
            logger .warning (f"VRM icon generation error: {e }")

    loop =asyncio .get_event_loop ()
    await loop .run_in_executor (None ,_generate_missing_icons_sync )


def _generate_missing_icons_sync ():
    """Sync icon generation for missing characters."""
    try :
        import yaml 
    except ImportError :
        return 
    char_dirs =sorted ([
    d for d in os .listdir (CHARACTERS_DIR )
    if os .path .isdir (os .path .join (CHARACTERS_DIR ,d ))
    ])
    generated =0 
    for idx ,char_dir in enumerate (char_dirs ):
        icon_path =os .path .join (CHARACTERS_DIR ,char_dir ,"icon.png")
        if os .path .exists (icon_path ):
            continue 
        index_path =os .path .join (CHARACTERS_DIR ,char_dir ,"index.yaml")
        name =char_dir 
        if os .path .exists (index_path ):
            try :
                with open (index_path ,'r')as f :
                    data =yaml .safe_load (f )or {}
                name =data .get ('name',char_dir )
            except Exception :
                logger .debug ("Could not parse character index %s",index_path )
        letter =name [0 ].upper ()if name else '?'
        color =PALETTE [idx %len (PALETTE )]
        if _generate_letter_icon (name ,letter ,color ,icon_path ):
            generated +=1 
    if generated :
        logger .debug (f"Generated {generated } character icon(s)")
