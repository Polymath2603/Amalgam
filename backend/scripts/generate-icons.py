
"""Generate 96x96 PNG character icons from characters/*/index.yaml.
Creates a colored icon with the character's initial letter.
Also generates the fallback logo.png."""

import os 
import sys 
import hashlib 
import yaml 
from PIL import Image ,ImageDraw ,ImageFont 

PROJECT_ROOT =os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))
CHARACTERS_DIR =os .path .join (PROJECT_ROOT ,"backend","characters")
ICONS_DIR =os .path .join (PROJECT_ROOT ,"frontend","webui","icons")
SIZE =96 
PADDING =8 


PALETTE =[
"#6c5ce7","#0984e3","#00b894","#e17055","#fd79a8",
"#f39c12","#00cec9","#e74c3c","#2ecc71","#3498db",
"#9b59b6","#1abc9c","#d35400","#c0392b","#16a085",
"#8e44ad","#27ae60","#2980b9","#f1c40f","#e67e22",
"#e84393","#00b894","#6c5ce7","#fd79a8","#0984e3",
"#00cec9","#e17055","#f39c12","#e74c3c","#2ecc71",
]


def get_color (name :str ,index :int )->str :
    """Get a deterministic color for a character."""
    return PALETTE [index %len (PALETTE )]


def hex_to_rgb (hex_color :str )->tuple :
    """Convert hex color to RGB tuple."""
    h =hex_color .lstrip ('#')
    return tuple (int (h [i :i +2 ],16 )for i in (0 ,2 ,4 ))


def lighten (color :tuple ,factor :float =0.3 )->tuple :
    """Lighten a color by blending with white."""
    return tuple (int (c +(255 -c )*factor )for c in color )


def darken (color :tuple ,factor :float =0.3 )->tuple :
    """Darken a color by blending with black."""
    return tuple (int (c *(1 -factor ))for c in color )


def draw_rounded_rect (draw ,bbox ,radius ,fill ):
    """Draw a rounded rectangle."""
    x0 ,y0 ,x1 ,y1 =bbox 
    draw .rectangle ([x0 +radius ,y0 ,x1 -radius ,y1 ],fill =fill )
    draw .rectangle ([x0 ,y0 +radius ,x1 ,y1 -radius ],fill =fill )
    draw .pieslice ([x0 ,y0 ,x0 +2 *radius ,y0 +2 *radius ],180 ,270 ,fill =fill )
    draw .pieslice ([x1 -2 *radius ,y0 ,x1 ,y0 +2 *radius ],270 ,360 ,fill =fill )
    draw .pieslice ([x0 ,y1 -2 *radius ,x0 +2 *radius ,y1 ],90 ,180 ,fill =fill )
    draw .pieslice ([x1 -2 *radius ,y1 -2 *radius ,x1 ,y1 ],0 ,90 ,fill =fill )


def generate_icon (name :str ,letter :str ,color_hex :str ,output_path :str ):
    """Generate a 96x96 PNG icon with a colored background and letter."""
    bg =hex_to_rgb (color_hex )
    bg_light =lighten (bg ,0.15 )
    bg_dark =darken (bg ,0.15 )

    img =Image .new ('RGBA',(SIZE ,SIZE ),(0 ,0 ,0 ,0 ))
    draw =ImageDraw .Draw (img )


    draw_rounded_rect (draw ,(0 ,0 ,SIZE -1 ,SIZE -1 ),16 ,bg )


    for i in range (3 ):
        alpha =40 -i *12 
        highlight =lighten (bg ,0.25 )
        draw_rounded_rect (draw ,(2 +i ,2 +i ,SIZE -3 -i ,SIZE -3 -i ),14 -i ,highlight +(alpha ,))


    try :
        font =ImageFont .truetype ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",44 )
    except (IOError ,OSError ):
        font =ImageFont .load_default ()

    bbox =draw .textbbox ((0 ,0 ),letter ,font =font )
    tw =bbox [2 ]-bbox [0 ]
    th =bbox [3 ]-bbox [1 ]
    x =(SIZE -tw )/2 -bbox [0 ]
    y =(SIZE -th )/2 -bbox [1 ]-2 


    draw .text ((x +1 ,y +1 ),letter ,fill =darken (bg ,0.4 )+(100 ,),font =font )

    draw .text ((x ,y ),letter ,fill =(255 ,255 ,255 ,230 ),font =font )

    img .save (output_path ,'PNG')
    print (f"  Generated: {output_path }")


def generate_logo (output_path :str ):
    """Generate the fallback logo.png (dark circle with face outline)."""
    img =Image .new ('RGBA',(SIZE ,SIZE ),(0 ,0 ,0 ,0 ))
    draw =ImageDraw .Draw (img )

    bg =hex_to_rgb ("#1a1a2e")
    draw_rounded_rect (draw ,(0 ,0 ,SIZE -1 ,SIZE -1 ),16 ,bg )


    stroke_color =(148 ,163 ,184 ,200 )


    draw .ellipse ([28 ,14 ,68 ,54 ],outline =stroke_color ,width =2 )


    draw .arc ([28 ,42 ,68 ,82 ],0 ,180 ,fill =stroke_color ,width =2 )


    draw .ellipse ([38 ,30 ,42 ,34 ],fill =stroke_color )
    draw .ellipse ([54 ,30 ,58 ,34 ],fill =stroke_color )


    draw .arc ([37 ,36 ,59 ,50 ],0 ,180 ,fill =stroke_color ,width =2 )

    img .save (output_path ,'PNG')
    print (f"  Generated: {output_path }")


def main ():
    print ("Generating character icons...")


    os .makedirs (ICONS_DIR ,exist_ok =True )
    logo_path =os .path .join (ICONS_DIR ,"logo.png")
    generate_logo (logo_path )


    char_dirs =sorted ([
    d for d in os .listdir (CHARACTERS_DIR )
    if os .path .isdir (os .path .join (CHARACTERS_DIR ,d ))
    ])

    for idx ,char_dir in enumerate (char_dirs ):
        char_path =os .path .join (CHARACTERS_DIR ,char_dir )
        index_path =os .path .join (char_path ,"index.yaml")
        icon_path =os .path .join (char_path ,"icon.png")



        if os .path .exists (icon_path ):
            print (f"  Skipping {char_dir } (icon.png exists)")
            continue 


        name =char_dir 
        if os .path .exists (index_path ):
            try :
                with open (index_path ,'r')as f :
                    data =yaml .safe_load (f )or {}
                name =data .get ('name',char_dir )
            except Exception :
                pass 


        letter =name [0 ].upper ()if name else '?'


        color =get_color (char_dir ,idx )

        generate_icon (name ,letter ,color ,icon_path )

    print (f"\nDone! Generated icons for {len (char_dirs )} characters.")
    print (f"Logo: {logo_path }")


if __name__ =="__main__":
    main ()
