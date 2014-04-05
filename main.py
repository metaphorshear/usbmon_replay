from usb1 import USBContext
from optparse import OptionParser
from subprocess import check_output
from re import findall
from struct import unpack
from libusb1 import USBError

def main():
	usage="""%prog [-dbtw] [-o <outfile>] [-f <filter>] <-i vendor:product || -n name> dumpfile"""
	"""
	Currently usbmon captures in text and raw form are supported. Note that you
	will need to filter them to only include the device that you are testing."""
	parser= OptionParser(usage, add_help_option=True)
	parser.add_option("-i", "--vendor-product-id", dest="vendor_product_id",
	help="specify the vendor and product ID in the form ####:####")
	parser.add_option("-n", "--name", dest="search_str",
	help="try to find a USB device by name or keywords")
	parser.add_option("-b", "--binary", action="store_true", dest="binary", help="binary usbmon from /dev/usbmon# or tcpdump")
	parser.add_option("-t", "--text", action="store_false", dest="binary", help="usbmon text dump (default)", default=False)
	parser.add_option("-d", "--dry-run", action="store_true", dest="dry_run", help="don't actually run anything; print stuff", default=False)
	parser.add_option("-f", "--filter", dest="filter", help="filter to assist in replaying the right packets")
	parser.add_option("-o", dest="filename", help="file to write device responses", default="response.log")
	parser.add_option("-w", "--interactive", dest="wait", action="store_true", help="pause after large responses", default=False)
	(options, args) = parser.parse_args()
	if len(args) < 1:
		parser.error("You need to provide at least one dumpfile")
	if options.vendor_product_id and options.search_str:
		print "--vendor-product-id and --name are mutually exclusive, so\
		 I'll assume you wanted --vendor-product-id"
		options.search_str = None
	if not (options.vendor_product_id or options.search_str):
		print "You have not provided a keyword nor a vendor and product id.\
		 I will try to select a device using your dumpfile, but this will probably fail."
	if options.vendor_product_id is None:
		if options.search_str is not None:
			try:
				vendor,product = find_by_name(options.search_str)
			except TypeError:
				vendor,product = None, None
		else:
			#try to get the device and bus from the dumpfile and use that
			vendor,product = None, None
	else:
		vendor,product = [int(i,16) for i in options.vendor_product_id.split(":")]
	for dumpfile in args:
		replay(vendor, product, dumpfile, options) 

def find_by_bus_device(bus, device, context):
	devs=context.getDeviceList()
	for dev in devs:
		if dev.getBusNumber() == bus and dev.getDeviceAddress() == device:
			return dev



def replay(vendor, product, dumpfile, options):
	context=USBContext()
	usbdev=None
	q=[]
	rewind=[]
	devices={}
	windbreak=False
	inc=["Ci","Co","Zi","Zo","Bi","Bo","Ii","Io"]
	if options.filter is not None:
		if "+" in options.filter:
			mi=options.filter.index("+")
			for i in xrange(len(inc)):
				if inc[i] not in options.filter:
					inc[i]=""
		while "" in inc:
			inc.remove("")
		if "-" in options.filter:
			mi=options.filter.index("-")
			for i in xrange(mi+1, len(options.filter), 2):
				try:
					inc.remove(options.filter[i:i+2])
				except ValueError:
					pass
		print "Only including devices that have", "|".join(inc), "traffic"
	if vendor is not None and product is not None:
		usbdev = context.openByVendorIDAndProductID(vendor, product)
		if usbdev is None:
			raise Exception("Unable to get the device.")
	if options.binary is False:
		inp=open(dumpfile, "r")
		lines=inp.readlines()
		if vendor is None:
			for line in lines:
				trans_bus_device = line.split()[3].split(':')
				if len(trans_bus_device) < 4:
					#it's going to be pretty hard to find this thing without a bus number
					raise Exception('There is not enough information to find the USB device. Please provide a vendor and product ID, or a keyword.')
				device,bus=int(trans_bus_device[-2]),int(trans_bus_device[-3])
				try:
					devices[(dev,bus)] += 1
				except KeyError:
					devices[(dev,bus)] = 1
			rdev,rbus=max(devices, key=lambda x: devices[x])
			usbdev=find_by_bus_device(rbus, rdev, context)
			if usbdev is None:
				raise Exception("Unable to get the device.")
		for line in lines:
			if "S" in line:
				data=""
				line=line.split()
				trans_type,bus,dev,endp=line[3].split(':')
				endp=int(endp)
				if trans_type in inc:
					try:
						devices[(dev,bus)] += 1
					except KeyError:
						devices[(dev,bus)] = 1
				q.append((dev,bus))
				if (trans_type == "Co" or trans_type == "Ci") and line[4] == 's':
					bmRequestType, bRequest, wValue, wIndex, wLength = [int(l, 16) for l in line[5:10]]
					if line[11] == '=':
						for li in line[12:]:
							for i in xrange(0, len(li), 2):
								data+=chr(int("0x"+li[i:i+2],16))
					if trans_type == "Co":
						q.append((usbdev.controlWrite, (bmRequestType, bRequest, wValue, wIndex, data, 200)))
					else:
						q.append((usbdev.controlRead, (bmRequestType, bRequest, wValue, wIndex, wLength, 200)))
				elif trans_type == "Bi":
					q.append((usbdev.bulkRead, (endp,int(line[5]),2000)))
				elif trans_type == "Bo":
					for li in line[7:]:
						for i in xrange(0, len(li), 2):
							data+=chr(int("0x"+li[i:i+2],16))
					q.append((usbdev.bulkWrite,(endp,data,2000)))
				#TODO: add interrupt and isosynchronous
	else:
		inp=open(dumpfile, "rb")
		header=inp.read(4)
		types={0:"Z", 1:"I", 2:"C", 3:"B"}
		dr={0:"o", 1:"i"}
		if header == "\xd4\xc3\xb2\xa1":
			#get rid of the tcpdump header, plus account for the timestamps
			pass
		else:
			header+=inp.read(44)
			while True:
				if len(header) < 40:
					break
				union=header[-8:] #this contains the data for ISO or Control S-type transfers
				length=unpack("<I", header[36:40])[0]
				data=inp.read(length)
				if header[8] == "S":
					trans_type=types[ord(header[9])]+dr[ord(header[10])>>7]
					endp=ord(header[10]) & 0xF
					dev,bus = ord(header[11]), unpack("<H", header[12:14])[0]
					q.append((dev,bus))
					if trans_type in inc: 
						try:
							devices[(dev,bus)] += 1
						except KeyError:
							devices[(dev,bus)] = 1
					if trans_type[0] == "C":
						bmRequestType, bRequest, wValue, wIndex, wLength=[ord(union[i]) for i in 0,1]+[unpack("<H", union[i:i+2])[0] for i in 2,4,6]
						if trans_type[1]=="i":
							q.append((usbdev.controlRead, (bmRequestType, bRequest, wValue, wIndex, wLength, 200)))
						else:
							q.append((usbdev.controlWrite, (bmRequestType, bRequest, wValue, wIndex, data, 200)))
					elif trans_type == "Ii":
						q.append((usbdev.interruptRead, (endp, length, 200)))
					elif trans_type == "Io":
						q.append((usbdev.interruptWrite, (endp, data, 200)))
					elif trans_type == "Bo":
						q.append((usbdev.bulkWrite,(endp,data,2000)))
					elif trans_type == "Bi":
						if length == 0:
							length = 1024
						q.append((usbdev.bulkRead, (endp,length,2000))) 
				header=inp.read(48)
	try:
		rdev,rbus=max(devices, key=lambda x: devices[x])
	except ValueError:
		print "No devices in the capture matched your criteria."
		exit(0)
	outp=open(options.filename, "wb")
	while q:
		try:
			dev,bus=q.pop(0)
			try:
				cmd,args=q.pop(0)
			except IndexError as e:
				print e
				print len(q)
				return
			if (dev != rdev) or (rbus != bus):
				continue
			if windbreak == False:
				rewind.append((dev,bus))
				rewind.append((cmd,args))
			if "control" in str(cmd):
				print "USB control transfer with type", hex(args[0]), "request", hex(args[1]), "value", hex(args[2])
			if "Write" in str(cmd):
				print "Sending",
				if "bulk" in str(cmd):
					print len(args[-2]), "bytes of data"
				else:
					print (args[-2]).encode("string_escape")
			else:
				print "Receiving", args[-2], "bytes of data"
			if options.dry_run == True:
				continue
			resp=cmd(*args)
			if isinstance(resp,int):
				if resp < args[-2]:
					pass
					#print "Warning: not all data made it to the device."
			else:
				outp.write(resp)
				print "Device response:"
				print resp.encode("string_escape")
				if len(resp) > 32:
					if options.wait == True:
						print "Continue? Yep/Nope/Stop pausing/Rewind <1-{0}>".format(len(rewind)/2)
						windbreak=False
						while True:
							_=raw_input()
							if len(_) < 1:
								break
							else:
								if (_[0] == "n" or _[0] == "N"):
									exit(0)
								elif (_[0] in ("S", "s", "P", "p")):
									options.wait = False
									break
								elif (_[0] in ("R", "r", "B", "b")):
									try:
										com,num=_.split()
										num=int(num)*2
										q=rewind[-num:] + q
										windbreak=True
										break
									except ValueError:
										print "Rewind Usage: [RrBb] <#number of steps>"
										continue
								else:
									break

		except KeyboardInterrupt:
			if options.wait == False:
				options.wait = True
			else:
				print "Exiting on keyboard interrupt."
				exit(0)
							
					
	
	

def find_by_name(search_str):
	out=check_output("lsusb").split('\n')
	for line in out:
		if search_str in line.lower():
			find=findall(r'[0-f]{4}\:[0-f]{4}', line)
			if find != []:
				return [int(i,16) for i in find[0].split(':')]
	raise Exception("No devices found matching your keywords.")
	
		
	
if __name__ == "__main__":
	main()



