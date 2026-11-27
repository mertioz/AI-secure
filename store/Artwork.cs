using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

internal static class Artwork
{
    private static Bitmap Logo(int size)
    {
        using (var master = new Bitmap(768, 768))
        using (var g = Graphics.FromImage(master))
        using (var contour = new Pen(Color.FromArgb(73, 218, 190), 6.5f))
        using (var trait = new Pen(Color.FromArgb(238, 249, 247), 7.5f))
        using (var bouclier = new GraphicsPath())
        {
            g.SmoothingMode = SmoothingMode.AntiAlias; g.ScaleTransform(6, 6);
            g.Clear(Color.FromArgb(19, 41, 57)); contour.LineJoin = LineJoin.Round;
            bouclier.AddLine(64, 18, 100, 31); bouclier.AddLine(100, 31, 100, 62);
            bouclier.AddBezier(100, 62, 100, 85, 83, 101, 64, 111);
            bouclier.AddBezier(64, 111, 45, 101, 28, 85, 28, 62);
            bouclier.AddLine(28, 62, 28, 31); bouclier.CloseFigure(); g.DrawPath(contour, bouclier);
            trait.StartCap = LineCap.Round; trait.EndCap = LineCap.Round; trait.LineJoin = LineJoin.Round;
            g.DrawLines(trait, new [] {new Point(46, 65), new Point(58, 77), new Point(82, 51)});
            var resultat = new Bitmap(size, size);
            using (var cible = Graphics.FromImage(resultat))
            {
                cible.InterpolationMode = InterpolationMode.HighQualityBicubic;
                cible.PixelOffsetMode = PixelOffsetMode.HighQuality;
                cible.DrawImage(master, 0, 0, size, size);
            }
            return resultat;
        }
    }

    private static byte[] Png(int size)
    {
        using (var image = Logo(size)) using (var flux = new MemoryStream())
        { image.Save(flux, ImageFormat.Png); return flux.ToArray(); }
    }

    private static void Main(string[] args)
    {
        string repertoire = args[0]; Directory.CreateDirectory(repertoire);
        File.WriteAllBytes(Path.Combine(repertoire, "Square44.png"), Png(44));
        File.WriteAllBytes(Path.Combine(repertoire, "Square150.png"), Png(150));
        File.WriteAllBytes(Path.Combine(repertoire, "StoreLogo.png"), Png(50));
        File.WriteAllBytes(args[1], Png(300));
        int[] tailles = { 16, 32, 48, 64, 128, 256 };
        byte[][] images = new byte[tailles.Length][];
        using (var fichier = new BinaryWriter(File.Create(Path.Combine(repertoire, "AISecure.ico"))))
        {
            fichier.Write((ushort)0); fichier.Write((ushort)1); fichier.Write((ushort)tailles.Length);
            int position = 6 + tailles.Length * 16;
            for (int i = 0; i < tailles.Length; i++)
            {
                images[i] = Png(tailles[i]);
                fichier.Write((byte)(tailles[i] % 256)); fichier.Write((byte)(tailles[i] % 256));
                fichier.Write((byte)0); fichier.Write((byte)0); fichier.Write((ushort)1); fichier.Write((ushort)32);
                fichier.Write(images[i].Length); fichier.Write(position); position += images[i].Length;
            }
            foreach (var image in images) fichier.Write(image);
        }
    }
}
