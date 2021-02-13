import os, io
from collections import OrderedDict
import argparse, logging

import img2pdf
from PIL import Image
from PyPDF2 import PdfFileReader, PdfFileWriter
from PyPDF2.generic import TextStringObject, NameObject
from PyPDF2.pdf import ContentStream
from PyPDF2.utils import b_
import matplotlib.pyplot as plt
import matplotlib.image as mpImage

def is_gray(a, b, c):
	r = 40
	if a + b + c < 350:
		return True
	if abs(a - b) > r:
		return False
	if abs(a - c) > r:
		return False
	if abs(b - c) > r:
		return False
	return True

class WatermarkRemoval:
	def __init__(self, args, logger=None):
		self.infile = args.input_pdf_path
		self.outfile = args.output
		self.is_scanned = args.scanned
		self.wmtext = args.text
		self.rm_image = args.i
		self.rm_text = self.wmtext is not None
		self.form = not args.form

		self.logger = logger

	def remove_watermark_from_scanned(self, image):
		image = image.convert("RGB")
		color_data = image.getdata()

		new_color = []
		for item in color_data:
			if is_gray(*item):
				new_color.append(item)
			else:
				new_color.append((255, 255, 255))
		image.putdata(new_color)
		return image

	def process_scanned_page(self, pg):
		content = pg['/Resources']['/XObject'] #.getObject()
		images = {}
		for obj in content:
			if content[obj]['/Subtype'] == '/Image':
				size = (content[obj]['/Width'], content[obj]['/Height'])
				data = content[obj]._data

				if content[obj]['/ColorSpace'] == '/DeviceRGB':
					mode = "RGB"
				else:
					mode = "P"
				if content[obj]['/Filter'] == '/FlateDecode':
					img = Image.frombytes(mode, size, data)
				else:
					img = Image.open(io.BytesIO(data))

				images[int(obj[2:])] = img
		images = OrderedDict(sorted(images.items())).values()
		widths, heights = zip(*(i.size for i in images))
		total_height = sum(heights)
		max_width = max(widths)
		concat_image = Image.new('RGB', (max_width, total_height))
		offset = 0
		for i in images:
			concat_image.paste(i, (0, offset))
			offset += i.size[1]
		if not skipped:
			concat_image = self.remove_watermark_from_scanned(concat_image)
		return concat_image

	def process_normal_page(self, pg, pdf):
		if self.rm_image:
			pg = self.remove_image_from_normal_page(pg)
		if self.rm_text:
			pg = self.remove_text_from_normal_page(pg, pdf)
		return pg

	def remove_image_from_normal_page(self, pg):
		content = pg['/Resources']['/XObject'].getObject()
		for obj in tuple(content.keys()):
			if content[obj]['/Subtype'] == '/Image':
				size = (content[obj]['/Width'], content[obj]['/Height'])
				data = content[obj]._data

				if content[obj]['/ColorSpace'] == '/DeviceRGB':
					mode = "RGB"
				else:
					mode = "P"

				try:
					img = Image.frombytes(mode, size, data)
				except ValueError:
					try:
						img = Image.open(io.BytesIO(data))
					except:
						try:
							img = Image.open(io.StringIO(data))
						except:
							img = None
				
				if self.ask_for_removal(img):
					del content[obj]

		pg['/Resources'][NameObject('/XObject')] = content
		return pg

	def remove_form_from_normal_page(self, pg):
		content = pg['/Resources']['/XObject'].getObject()
		for obj in tuple(content.keys()):
			if (content[obj]['/Subtype'] == '/Form' and 
				'/BBox' in content[obj] and
				'/Text' in content[obj]['/Resources']['/ProcSet']):
				del content[obj]
		pg['/Resources'][NameObject('/XObject')] = content
		return pg

	def remove_text_from_normal_page(self, pg, pdf):
		content_object = pg["/Contents"].getObject()
		content = ContentStream(content_object, pdf)
		flag = False
		for operands, operator in content.operations:
			if operator in [b_('TJ'), b_('Tj')]:
				if type(operands[0]) is list:
					text = ''.join(map(lambda x: x if isinstance(x, TextStringObject) else '', operands[0]))
				else: text = operands[0]
				if isinstance(text, TextStringObject) and text.startswith(self.wmtext):
					operands[0] = TextStringObject('')
					flag = True
		pg[NameObject('/Contents')] = content
		if not flag and self.form:
			pg = self.remove_form_from_normal_page(pg)
		return pg

	def ask_for_removal(self, image):
		if image is None: 
			ans = input('Cannot display image unfortunately. Shall we try to remove it or not? y/n: ').lower()
		else:
			plt.imshow(mpImage.pil_to_array(image))
			plt.show(block=False)
			ans = input('Should we remove this image? y/n: ').lower()
		return ans == 'y'

	def process_normal_document(self):
		with open(self.infile, "rb") as f:
			pdf = PdfFileReader(f)
			out = PdfFileWriter()

			for i in range(pdf.getNumPages()):
				self.logger.info("Processing page {}/{}".format(i + 1, pdf.getNumPages()))
				out.insertPage(
					self.process_normal_page(pdf.getPage(i), pdf))

			with open(self.outfile, "wb") as of:
				out.write(of)

		self.logger.info('Done')

	def process_scanned_document(self):
		imname = 'temp1234.jpg'

		with open(self.infile, "rb") as f:
			pdf = PdfFileReader(f)
			out = PdfFileWriter()
			for i in range(pdf.getNumPages()):
				self.logger.info("Processing page {}/{}".format(i + 1, pdf.getNumPages()))
				self.process_scanned_page(pdf.getPage(i)).save(imname)
				out.write(img2pdf.convert(img2pdf.input_images(imname)))

		with open(self.outfile, "wb") as of:
			out.write(of)
		self.logger.info('Done')

	def process_document(self):
		if self.is_scanned: 
			self.process_scanned_document()
			return
		self.process_normal_document()

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('input_pdf_path', metavar='PATH')
	parser.add_argument('-o', '--output', metavar='out',
		default='out.pdf', help='Output PDF file')
	parser.add_argument('--scanned', dest='scanned', action='store_true',
		help='Document contains scanned pages')
	parser.add_argument('-i', dest='i', action='store_true',
		help='Remove image watermark')
	parser.add_argument('--text', help='Textual watermark to be removed')
	parser.add_argument('--skip-form', dest='form', action='store_true',
		help='Do not try to remove form object if text not found. \nTry this flag if attempt without this flag resulted in removing wrong items, but the tool may remain unsuccessful')
	args = parser.parse_args()

	logger = logging.getLogger(__name__)
	logging.basicConfig(level='INFO', format='%(asctime)s - %(levelname)s - %(message)s')

	rem = WatermarkRemoval(args, logger)
	rem.process_document()