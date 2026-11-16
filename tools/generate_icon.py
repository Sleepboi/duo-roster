from pathlib import Path
from PIL import Image,ImageDraw

root=Path(__file__).resolve().parents[1]
image=Image.new('RGBA',(256,256),(0,0,0,0));draw=ImageDraw.Draw(image)
draw.rounded_rectangle((10,10,246,246),radius=38,fill='#33465F')
draw.rounded_rectangle((24,56,232,232),radius=21,fill='#FFFFFF')
draw.rounded_rectangle((56,0,75,45),radius=9,fill='#8194A9')
draw.rounded_rectangle((181,0,200,45),radius=9,fill='#8194A9')
for box,color in [((43,81,119,143),'#57B874'),((137,81,213,143),'#D8EF9A'),((43,156,119,218),'#8FC4F1'),((137,156,213,218),'#F8B26B')]:
    draw.rounded_rectangle(box,radius=9,fill=color)
assets=root/'assets';assets.mkdir(exist_ok=True)
image.save(assets/'duoroster.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
