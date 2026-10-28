//! Native 1080x1920 share artwork, equivalent to the legacy PIL Spin Report.
//! The only external asset requests are public album-cover CDNs.
use crate::api::App;
use anyhow::{Context, Result};
use fontdue::{Font, FontSettings};
use image::{Rgb, RgbImage, imageops::FilterType};
use serde_json::Value;
use std::path::Path;

const W: u32 = 1080;
const H: u32 = 1920;
const INK: [u8; 3] = [13, 15, 22];
const PANEL: [u8; 3] = [24, 26, 35];
const SURFACE: [u8; 3] = [16, 18, 26];
const BORDER: [u8; 3] = [62, 66, 83];
const WHITE: [u8; 3] = [239, 240, 245];
const MUTED: [u8; 3] = [159, 164, 180];

struct Fonts { normal: Font, bold: Font, pixel: Font }
fn load_font(root: &Path, candidates: &[&str]) -> Result<Font> {
    for path in candidates {
        let p = if path.starts_with('/') { Path::new(path).to_path_buf() } else { root.join(path) };
        if let Ok(bytes) = std::fs::read(p)
            && let Ok(font) = Font::from_bytes(bytes, FontSettings::default()) {
                return Ok(font);
            }
    }
    anyhow::bail!("No usable image font found")
}
impl Fonts {
    fn new(root: &Path) -> Result<Self> {
        Ok(Self {
            normal: load_font(root, &["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "assets/fonts/Pixel Millennium.ttf"] )?,
            bold: load_font(root, &["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf", "assets/fonts/Pixel Millennium.ttf"] )?,
            pixel: load_font(root, &["assets/fonts/VCR_OSD_MONO_1.001.ttf", "assets/fonts/vinylpixel.ttf"] )?,
        })
    }
}
struct Poster { img: RgbImage, fonts: Fonts, accent: [u8; 3] }
impl Poster {
    fn new(root: &Path, accent: [u8; 3]) -> Result<Self> {
        Ok(Self { img: RgbImage::from_pixel(W,H,Rgb(INK)), fonts: Fonts::new(root)?, accent })
    }
    fn rect(&mut self,x:i32,y:i32,w:i32,h:i32,c:[u8;3]) {
        for yy in y.max(0)..(y+h).min(H as i32) {
            for xx in x.max(0)..(x+w).min(W as i32) { self.img.put_pixel(xx as u32,yy as u32,Rgb(c)); }
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn rounded(&mut self,x:i32,y:i32,w:i32,h:i32,r:i32,c:[u8;3],border:Option<[u8;3]>) {
        let r = r.min(w/2).min(h/2);
        for yy in y.max(0)..(y+h).min(H as i32) {
            for xx in x.max(0)..(x+w).min(W as i32) {
                let dx = (x+r-xx).max(0).max(xx-(x+w-r-1));
                let dy = (y+r-yy).max(0).max(yy-(y+h-r-1));
                if dx*dx+dy*dy > r*r { continue; }
                let edge = border.is_some() && (xx-x<2 || x+w-xx<=2 || yy-y<2 || y+h-yy<=2 || dx*dx+dy*dy>(r-2)*(r-2));
                self.img.put_pixel(xx as u32,yy as u32,Rgb(if edge {border.unwrap_or(c)} else {c}));
            }
        }
    }
    fn circle(&mut self,cx:i32,cy:i32,r:i32,c:[u8;3],stroke:bool) {
        for yy in (cy-r).max(0)..=(cy+r).min(H as i32-1) {
            let dy=yy-cy;
            let dx=((r*r-dy*dy) as f64).sqrt() as i32;
            if stroke {
                for x in [cx-dx,cx+dx] { if (0..W as i32).contains(&x) { self.img.put_pixel(x as u32,yy as u32,Rgb(c)); } }
            } else { self.rect(cx-dx,yy,2*dx+1,1,c); }
        }
    }
    fn font(&self, variant: u8) -> &Font {match variant {1=>&self.fonts.bold,2=>&self.fonts.pixel,_=>&self.fonts.normal}}
    fn width(&self,text:&str,size:f32,variant:u8)->i32 {
        text.chars().map(|c|self.font(variant).metrics(c,size).advance_width).sum::<f32>().ceil() as i32
    }
    fn fit(&self,text:&str,size:f32,variant:u8,max:i32)->String {
        if self.width(text,size,variant)<=max {return text.to_owned()}
        let mut s=String::new();
        for ch in text.chars(){
            let next=format!("{s}{ch}…");
            if self.width(&next,size,variant)>max {break;}
            s.push(ch);
        }
        format!("{s}…")
    }
    fn text(&mut self,x:i32,y:i32,text:&str,size:f32,variant:u8,color:[u8;3]) {
        let mut at=x as f32;
        for ch in text.chars() {
            let (metrics,bitmap)=self.font(variant).rasterize(ch,size);
            // Fontdue raster bitmap starts at its glyph top; position against a
            // stable text line rather than relying on a platform-specific baseline.
            let top=y+(size as i32-metrics.height as i32)/2;
            for by in 0..metrics.height {
                let dy=top+by as i32;
                if !(0..H as i32).contains(&dy){continue;}
                for bx in 0..metrics.width {
                    let dx=at as i32+metrics.xmin+bx as i32;
                    if !(0..W as i32).contains(&dx){continue;}
                    let a=bitmap[by*metrics.width+bx] as u16;
                    if a==0{continue;}
                    let p=self.img.get_pixel_mut(dx as u32,dy as u32);
                    for (n,v) in color.iter().enumerate(){p.0[n]=((p.0[n] as u16*(255-a)+*v as u16*a)/255) as u8;}
                }
            }
            at+=metrics.advance_width;
        }
    }
    fn right(&mut self,right:i32,y:i32,text:&str,size:f32,variant:u8,color:[u8;3]) {
        self.text(right-self.width(text,size,variant),y,text,size,variant,color)
    }
    fn panel(&mut self,x:i32,y:i32,w:i32,h:i32){self.rounded(x,y,w,h,28,PANEL,Some(BORDER));}
    fn ranked(&mut self,title:&str,items:&[Value],x:i32,y:i32,unit:&str) {
        self.panel(x,y,457,556);
        self.text(x+26,y+22,title,27.,1,WHITE);
        self.right(x+427,y+27,unit,17.,2,self.accent);
        for i in 0..5 {
            let yy=y+88+i*83;
            self.rounded(x+18,yy,421,73,14,SURFACE,None);
            self.text(x+29,yy+22,&format!("{:02}",i+1),19.,1,self.accent);
            let item=items.get(i);
            let name=item.and_then(|v|v["name"].as_str()).unwrap_or("—");
            let count=item.and_then(|v|v["count"].as_i64()).map(|v|v.to_string()).unwrap_or_else(||"—".to_owned());
            let label=self.fit(name,20.,1,285);
            self.text(x+69,yy+22,&label,20.,1,WHITE);
            self.right(x+424,yy+18,&count,27.,1,self.accent);
        }
    }
    fn placeholder_cover(&mut self,x:i32,y:i32){
        self.rounded(x,y,160,160,11,[37,39,49],None);
        self.circle(x+80,y+80,66,SURFACE,false);
        for radius in (18..66).step_by(11){self.circle(x+80,y+80,radius,BORDER,true)}
        self.circle(x+80,y+80,26,self.accent,false);
    }
}
fn accent(scope:&str)->[u8;3]{match scope{"spotify"=>[63,206,131],"combined"=>[157,131,241],_=>[245,197,66]}}
fn duration(seconds:f64)->String {
    let mins=(seconds.max(0.)/60.).round() as u64;
    if mins>=60 {format!("{} h {:02} min",mins/60,mins%60)}else{format!("{mins} min")}
}
async fn cover(client:&reqwest::Client, url:&str)->Option<RgbImage> {
    let parsed=url::Url::parse(url).ok()?;
    if parsed.scheme()!="https" {return None;}
    let host=parsed.host_str()?.to_ascii_lowercase();
    // The URL originates in metadata and may be controlled by remote APIs.
    // Never fetch private addresses or untrusted hosts in a backend endpoint.
    if !["mzstatic.com","scdn.co","discogs.com","discogsusercontent.com","coverartarchive.org","musicbrainz.org"].iter().any(|domain|host==*domain||host.ends_with(&format!(".{domain}"))){return None;}
    let response=client.get(parsed).timeout(std::time::Duration::from_secs(4)).send().await.ok()?;
    if !response.status().is_success() || response.content_length().is_some_and(|l|l>3_000_000){return None;}
    let bytes=response.bytes().await.ok()?;
    if bytes.len()>3_000_000{return None;}
    let img=image::load_from_memory(&bytes).ok()?;
    Some(img.resize_to_fill(160,160,FilterType::Lanczos3).to_rgb8())
}

pub async fn render(app:&App, scope:&str, year:Option<i32>)->Result<Vec<u8>> {
    let stats=app.db.stats(scope,year)?;
    let accent=accent(scope);
    let mut p=Poster::new(&app.root,accent)?;
    let cover_client=reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(4)).build()?;
    // The subtle record engraving in the top right mirrors the legacy image.
    for radius in (130..550).step_by(10) {
        p.circle(912,235,radius,if radius%40==0 {[40,43,54]}else{[30,32,42]},true);
    }
    p.circle(912,235,57,BORDER,false);
    p.circle(912,235,53,[27,29,38],false);
    p.circle(912,235,8,accent,false);
    p.rect(72,41,936,5,accent);
    p.text(72,68,"VINYLPI64",22.,2,accent);
    p.right(1008,70,"LISTENING STATS",17.,2,MUTED);
    p.rect(72,119,936,2,BORDER);
    p.text(72,144,"Spin Report",76.,1,WHITE);
    p.text(76,263,&year.map_or("ALL TIME".to_owned(),|y|y.to_string()),26.,2,MUTED);
    let pill=scope.to_ascii_uppercase();
    let pw=p.width(&pill,23.,1);
    p.rounded(73,325,54+pw,55,15,accent,None);
    p.text(95,337,&pill,23.,1,INK);
    // Profile integration intentionally omitted during backend migration.

    p.panel(72,409,936,280);
    p.text(105,447,"TOTAL LISTENING TIME",21.,2,accent);
    let minutes=stats["total_minutes_listened"].as_i64().unwrap_or(0).to_string();
    let digits=p.fit(&minutes,if minutes.len()>6 {90.}else{116.},1,520);
    p.text(98,483,&digits,if minutes.len()>6 {90.}else{116.},1,WHITE);
    p.text(106,615,"minutes listened",28.,0,MUTED);
    p.rect(652,453,2,194,BORDER);
    if scope=="vinyl" {
        p.text(689,490,"PICKUP USAGE",19.,2,accent);
        p.text(689,540,&duration(stats["pickup_usage_seconds"].as_f64().unwrap_or(0.)),30.,1,WHITE);
        p.text(689,598,"USB audio activity",19.,0,MUTED);
    } else {
        p.text(689,490,"SOURCE",19.,2,accent);
        p.text(689,540,if scope=="spotify" {"Spotify"} else {"Vinyl + Spotify"},27.,1,WHITE);
        p.text(689,598,"Listening history",19.,0,MUTED);
    }
    p.panel(72,712,936,314);
    p.text(100,738,"IN ROTATION",23.,1,WHITE);
    p.right(979,743,"TOP ALBUM ART",17.,2,accent);
    let albums=stats["top_album_covers"].as_array().cloned().unwrap_or_default();
    for (i,x) in [94,398,702].iter().enumerate() {
        p.rounded(*x,787,284,215,17,SURFACE,Some([44,48,61]));
        p.placeholder_cover(*x+62,796);
        if let Some(url)=albums.get(i).and_then(|v|v["cover_url"].as_str())
            && let Some(img)=cover(&cover_client,url).await {
                image::imageops::overlay(&mut p.img,&img,(*x+62) as i64,796);
            }
        let name=albums.get(i).and_then(|v|v["name"].as_str()).unwrap_or("—");
        let title=p.fit(name,18.,1,245);
        let tx=*x+(284-p.width(&title,18.,1))/2;
        p.text(tx,962,&title,18.,1,WHITE);
    }
    let artists=stats["top_artists"].as_array().cloned().unwrap_or_default();
    let albums=stats["top_albums"].as_array().cloned().unwrap_or_default();
    p.ranked("Top 5 artists",&artists,72,1052,"PLAYS");
    let unit=if scope=="vinyl"{"SESSIONS"}else{"LISTENS"};
    p.ranked("Top 5 albums",&albums,551,1052,unit);
    p.panel(72,1632,936,216);
    p.text(100,1654,"TOP GENRES",26.,1,WHITE);
    p.right(979,1660,"PLAYS",17.,2,accent);
    let genres=stats["top_genres"].as_array().cloned().unwrap_or_default();
    if genres.is_empty(){p.text(104,1733,"No genre data available yet.",23.,0,MUTED);}
    for (i,g) in genres.iter().take(5).enumerate() {
        let col=if i<3 {0} else {1};
        let row=if col==0{i}else{i-3};
        let x=if col==0{103}else{559};
        let y=1704+row as i32*45;
        p.text(x,y,&format!("{:02}",i+1),20.,1,accent);
        let label=p.fit(g["name"].as_str().unwrap_or("Unknown"),21.,1,310);
        p.text(x+44,y,&label,21.,1,WHITE);
        p.right(x+413,y,&g["count"].as_i64().unwrap_or(0).to_string(),21.,1,accent);
    }
    p.rect(72,1880,936,2,BORDER);
    p.text(74,1889,"VINYLPI64",17.,2,accent);
    p.right(1006,1889,&format!("SOURCE / {}",scope.to_uppercase()),16.,2,MUTED);
    crate::display::png(p.img).context("PNG encoding failed")
}
